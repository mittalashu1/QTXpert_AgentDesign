"""Authenticated API endpoints for the unified Autopilot target runner."""
import asyncio
import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID, uuid4
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.autopilot_execution import AutopilotExecution
from app.database.models.autopilot_input import AutopilotInputRecord
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.document_intelligence import DocumentAnalysisRun
from app.database.models.uploaded_asset import UploadedAsset
from app.database.models.user import User
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import AsyncSessionLocal, get_db_session
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAnalysisRerunRequest,
    AutopilotAutomationBundle,
    AutopilotContextRequest,
    AutopilotContextResponse,
    AutopilotDiscoveryRequest,
    AutopilotDiscoveryResult,
    AutopilotExecutionRecord,
    AutopilotExecutionRequest,
    AutopilotExecutionResult,
    AutopilotJobStatus,
    AutopilotProviderStatus,
    AutopilotProfileOption,
    AutopilotReportDeletionResult,
    AutopilotResumeRequest,
    AutopilotSurface,
    AutopilotSetupProfile,
    AutopilotSetupUpdateRequest,
    AutopilotTestAuditReport,
    AutopilotSuiteRequest,
    AutopilotSuiteResult,
)
from app.schemas.upload_repository import ReuseUploadedAssetRequest
from app.services.autopilot import (
    AutopilotPrototypeService,
    AutopilotUploadInvalid,
    AutopilotUploadTooLarge,
    build_report_tab_key,
    _is_uuid,
    build_surface_key,
    normalize_surface_identity,
)
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_web import AutopilotWebService
from app.services.autopilot_context import default_context, get_profile, list_profiles
from app.services.autopilot_ir import AutopilotIRCompiler, build_input_requests, credential_value_available
from app.services.autopilot_report import build_test_audit_report
from app.services.autopilot_suite import AutopilotSuiteService
from app.services.autopilot_input_store import AutopilotInputStoreError, apply_submissions, list_metadata
from app.services.document_processor import UnsupportedDocumentTypeError, extract_text
from app.services.document_intelligence import DocumentIntelligenceService
from app.services.upload_repository import (
    UploadRepositoryInvalid,
    UploadRepositoryService,
    UploadRepositoryStorageUnavailable,
    UploadRepositoryTooLarge,
)

router = APIRouter(prefix="/autopilot", tags=["autopilot"])
logger = logging.getLogger(__name__)
_REPOSITORY_MATERIALIZATION_TASKS: set[str] = set()


def _service(settings: Settings) -> AutopilotPrototypeService:
    return AutopilotPrototypeService(settings)


async def _materialize_repository_asset_and_analyze(
    settings: Settings,
    job_id: str,
    asset_id: UUID,
    owner_id: UUID,
) -> None:
    """Materialize a reusable mobile build after the 202 response is sent.

    Stored APK/IPA reuse must not hold the HTTP request open while a large R2
    object is copied to the worker. The task is idempotent so a status poll or
    process-restart recovery can safely enqueue it again.
    """
    service = _service(settings)
    try:
        # Clear only orphaned atomic-write files before starting another large
        # repository copy. Durable job manifests and source assets remain
        # untouched and can be reused for a retry.
        await service.cleanup_local_staging()
        logger.info(
            "Autopilot repository materialization started job_id=%s asset_id=%s",
            job_id,
            asset_id,
        )
        job = await service.load_job(job_id)
        if job.get("status") in {"analyzed", "failed", "superseded"}:
            return
        target = Path(job.get("apk_path") or service.root / job_id / Path(job.get("filename") or "application.apk").name)
        if not target.is_file():
            await service.update_job(job_id, artifact_materialization="materializing")
            async with AsyncSessionLocal() as session:
                await UploadRepositoryService.materialize(
                    session,
                    asset_id,
                    owner_id,
                    target,
                    settings=settings,
                )
        await service.update_job(
            job_id,
            apk_path=str(target),
            artifact_materialization="complete",
        )
        await service.analyze_safely(job_id)
        final_job = await service.load_job(job_id)
        logger.info(
            "Autopilot repository materialization and analysis finished job_id=%s asset_id=%s status=%s",
            job_id,
            asset_id,
            final_job.get("status"),
        )
    except Exception as exc:  # pragma: no cover - provider/storage specific
        logger.exception("Autopilot repository materialization failed job_id=%s asset_id=%s", job_id, asset_id)
        try:
            await service.update_job(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                error=(
                    "The stored mobile artifact could not be materialized for analysis. "
                    f"{type(exc).__name__}: {str(exc)[:700]}"
                ),
                artifact_materialization="failed",
            )
        except Exception:  # pragma: no cover - defensive local fallback
            logger.exception("Autopilot repository materialization failure could not be recorded job_id=%s", job_id)
    finally:
        _REPOSITORY_MATERIALIZATION_TASKS.discard(job_id)


def _queue_repository_materialization(
    background_tasks: BackgroundTasks,
    settings: Settings,
    job_id: str,
    asset_id: UUID,
    owner_id: UUID,
) -> None:
    """Queue one materialization task per in-process job."""
    if job_id in _REPOSITORY_MATERIALIZATION_TASKS:
        return
    _REPOSITORY_MATERIALIZATION_TASKS.add(job_id)
    logger.info(
        "Autopilot repository materialization queued job_id=%s asset_id=%s",
        job_id,
        asset_id,
    )
    background_tasks.add_task(
        _materialize_repository_asset_and_analyze,
        settings,
        job_id,
        asset_id,
        owner_id,
    )


async def _prepare_resume_target(
    settings: Settings,
    job_id: str,
    owner_id: UUID,
) -> str:
    """Ensure a mobile source is present before a background resume.

    The HTTP request and its BackgroundTask can observe different lifecycle
    points around a Render restart.  Materializing here makes resume safe even
    when the request could read a durable analysis but the worker cannot see
    the disposable APK path.
    """
    service = _service(settings)
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == owner_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autopilot owner was not found")
        job = await _require_owned_job(service, job_id, user)
        target_kind = str(job.get("target_kind") or "android")
        if target_kind != "web":
            await _ensure_local_artifact(db, service, job_id, user)
        return target_kind


async def _resume_analysis_background(
    settings: Settings,
    job_id: str,
    owner_id: UUID,
) -> None:
    """Resume a checkpoint after preparing any repository-backed artifact."""
    service = _service(settings)
    try:
        await _prepare_resume_target(settings, job_id, owner_id)
        await service.resume_analysis(job_id)
    except Exception as exc:  # pragma: no cover - provider/storage specific
        logger.exception("Autopilot background resume failed job_id=%s", job_id)
        try:
            await service.update_job(
                job_id,
                status="failed",
                stage="failed",
                progress=100,
                error=(
                    "Autopilot could not resume the saved checkpoint. "
                    f"{type(exc).__name__}: {str(exc)[:700]}"
                ),
            )
        except Exception:
            logger.exception("Autopilot background resume failure could not be recorded job_id=%s", job_id)


def _effective_context(
    value: Optional[str],
    profile_id: str = "uae_fintech",
    *,
    target_kind: str = "android",
    target_url: str | None = None,
    application_name: str | None = None,
) -> str:
    """Ensure every entry point uses a safe context, including direct API clients."""
    cleaned = (value or "").strip()
    if cleaned:
        return cleaned[:8000]
    platform = "Web" if target_kind == "web" else "iOS" if target_kind == "ios" else "Android"
    return default_context(
        application_name=application_name,
        platform=platform,
        profile_id=profile_id,
        target_url=target_url,
    )


def _parse_document_asset_ids(value: object) -> list[UUID]:
    """Parse the JSON form field used by the multipart Autopilot endpoint."""
    if value is None or value == "":
        return []
    parsed: object = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document_asset_ids must be a JSON array") from exc
    if not isinstance(parsed, list):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document_asset_ids must be a JSON array")
    if len(parsed) > 20:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select at most 20 supporting documents")
    result: list[UUID] = []
    for item in parsed:
        try:
            asset_id = UUID(str(item))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more supporting document IDs are invalid") from exc
        if asset_id not in result:
            result.append(asset_id)
    return result


def _merge_document_asset_ids(*groups: list[UUID] | None) -> list[UUID]:
    """Merge document selections while respecting Autopilot's 20-document limit.

    A Document Intelligence baseline can contribute its own source assets in
    addition to documents selected in the Autopilot form.  Keep the baseline
    first (so its reviewed evidence is never dropped), de-duplicate IDs, and
    cap the combined selection at the same limit enforced by the form parser.
    """
    result: list[UUID] = []
    for group in groups:
        for asset_id in group or []:
            if asset_id in result:
                continue
            result.append(asset_id)
            if len(result) >= 20:
                return result
    return result


def _redact_document_excerpt(value: str) -> str:
    """Keep obvious credential values out of the model context."""
    # Keep Autopilot's document excerpts on the same redaction path as
    # Document Intelligence. This covers plain text, JSON/YAML key-value
    # pairs and bearer tokens without duplicating divergent regexes.
    return DocumentIntelligenceService._redact_sensitive_text(value)


async def _document_context(
    db: AsyncSession,
    user: User,
    project_id: Optional[UUID],
    document_asset_ids: list[UUID],
    settings: Settings,
) -> tuple[list[UUID], str]:
    """Validate selected repository documents and build a bounded context excerpt."""
    if not document_asset_ids:
        return [], ""
    query = select(UploadedAsset).where(
        UploadedAsset.id.in_(document_asset_ids),
        UploadedAsset.owner_id == user.id,
        UploadedAsset.status == "ready",
    )
    if project_id is not None:
        query = query.where(UploadedAsset.project_id == project_id)
    assets = [asset for asset in (await db.scalars(query)).all() if UploadRepositoryService.is_reusable_document(asset)]
    assets_by_id = {asset.id: asset for asset in assets}
    if len(assets_by_id) != len(document_asset_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more supporting documents were not found in this project")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    excerpts: list[str] = []
    total_bytes = 0
    for asset_id in document_asset_ids:
        asset = assets_by_id[asset_id]
        chunks: list[bytes] = []
        asset_bytes = 0
        try:
            async for chunk in UploadRepositoryService.iter_content(db, asset.id, settings=settings):
                asset_bytes += len(chunk)
                total_bytes += len(chunk)
                if asset_bytes > max_bytes or total_bytes > max_bytes * 2:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Supporting documents exceed the {settings.MAX_UPLOAD_SIZE_MB * 2}MB analysis context limit",
                    )
                chunks.append(chunk)
            text = extract_text(asset.filename, b"".join(chunks))
        except UnsupportedDocumentTypeError:
            # Keep the asset auditable even if its contents are not text
            # extractable; the target and user context still drive analysis.
            text = ""
        except UploadRepositoryStorageUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="File storage is temporarily unavailable; retry after repository access recovers.",
            ) from exc
        safe_text = _redact_document_excerpt(text).strip()
        if safe_text:
            excerpts.append(f"[Repository document: {asset.filename}]\n{safe_text[:5000]}")
        else:
            excerpts.append(f"[Repository document: {asset.filename}]\nContent is stored in the project repository; text extraction is unavailable for this asset.")

    return document_asset_ids, "\n\n".join(excerpts)


def _context_with_documents(
    base_context: Optional[str],
    profile_id: str,
    document_excerpt: str,
    *,
    target_kind: str = "android",
    target_url: str | None = None,
    application_name: str | None = None,
) -> str:
    context = _effective_context(
        base_context,
        profile_id,
        target_kind=target_kind,
        target_url=target_url,
        application_name=application_name,
    )
    if not document_excerpt:
        return context
    prefix = f"{context[:6000]}\n\nSelected repository documentation:\n"
    return (prefix + document_excerpt)[:8000]


async def _document_analysis_baseline(
    db: AsyncSession,
    user: User,
    settings: Settings,
    run_id: UUID | None,
    project_id: UUID | None,
) -> tuple[UUID | None, list[UUID], str]:
    """Load a completed Document Intelligence baseline for a downstream run."""
    if run_id is None:
        return None, [], ""
    try:
        analysis_run = await DocumentIntelligenceService(db, settings).get_run(run_id, user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document Intelligence baseline not found") from exc
    if project_id is not None and analysis_run.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document Intelligence baseline is not in this project")
    if analysis_run.status != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Complete the Document Intelligence review before using its baseline")
    payload = DocumentIntelligenceService(db, settings).build_context_payload(analysis_run)
    # Autopilot accepts at most twenty supporting documents per run. The
    # baseline itself remains complete and auditable; only the prompt-side
    # attachment list is bounded here.
    return run_id, list(payload.get("asset_ids") or [])[:20], str(payload.get("context") or "")


def _context_without_documents(value: Optional[str]) -> str:
    """Recover the editable user/profile brief from a stored effective context."""
    return (value or "").split("\n\nSelected repository documentation:", 1)[0].strip()


def _canonical_profile_id(profile_id: str | None) -> str:
    return get_profile(profile_id).id


def _profile_id_from_legacy_context(value: object, fallback: str | None = None) -> str:
    """Recover a profile for jobs created before surface columns existed."""
    text = str(value or "")
    marker = re.search(r"^Profile category:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if marker:
        requested = marker.group(1).strip().casefold()
        for profile in list_profiles():
            if profile.name.casefold() == requested:
                return profile.id
    return _canonical_profile_id(fallback)


def _record_surface_key(record: AutopilotJob) -> tuple[str, str, str, str]:
    """Return profile, target kind, identity and key for old or new rows."""
    target_kind = str(getattr(record, "target_kind", None) or "android").lower()
    if target_kind not in {"android", "ios", "web"}:
        target_kind = "android"
    profile_id = _profile_id_from_legacy_context(
        getattr(record, "context", None), getattr(record, "profile_id", None)
    )
    identity = str(getattr(record, "surface_identity", None) or "")
    if not identity:
        analysis = getattr(record, "analysis", None) or {}
        identity = normalize_surface_identity(
            target_kind,
            target_url=getattr(record, "target_url", None),
            artifact_sha256=analysis.get("sha256") if isinstance(analysis, dict) else None,
            filename=getattr(record, "filename", None),
        )
    key = str(getattr(record, "surface_key", None) or build_surface_key(profile_id, target_kind, identity))
    return profile_id, target_kind, identity, key


def _local_surface_key(job: dict) -> tuple[str, str, str, str]:
    """Return the same surface identity for a filesystem-only legacy job."""
    target_kind = str(job.get("target_kind") or "android").lower()
    if target_kind not in {"android", "ios", "web"}:
        target_kind = "android"
    profile_id = _profile_id_from_legacy_context(job.get("context"), job.get("profile_id"))
    identity = str(job.get("surface_identity") or "")
    if not identity:
        analysis = job.get("analysis") or {}
        identity = normalize_surface_identity(
            target_kind,
            target_url=job.get("target_url"),
            artifact_sha256=(analysis.get("sha256") if isinstance(analysis, dict) else None) or job.get("_analysis_sha256"),
            filename=job.get("filename"),
        )
    key = str(job.get("surface_key") or build_surface_key(profile_id, target_kind, identity))
    return profile_id, target_kind, identity, key


def _surface_details(
    profile_id: str | None,
    target_kind: str,
    *,
    target_url: str | None = None,
    artifact_sha256: str | None = None,
    filename: str | None = None,
) -> tuple[str, str, str]:
    """Return canonical profile, human-readable identity and indexed key."""
    canonical_profile = _canonical_profile_id(profile_id)
    identity = normalize_surface_identity(
        target_kind,
        target_url=target_url,
        artifact_sha256=artifact_sha256,
        filename=filename,
    )
    return canonical_profile, identity, build_surface_key(canonical_profile, target_kind, identity)


async def _upload_sha256(upload: UploadFile, max_bytes: int = 0) -> str:
    """Hash an uploaded binary in bounded chunks and rewind it for persistence."""
    hasher = hashlib.sha256()
    await upload.seek(0)
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if max_bytes and total > max_bytes:
            await upload.seek(0)
            raise AutopilotUploadTooLarge(
                f"Mobile artifact exceeds the {max_bytes // (1024 * 1024)}MB Autopilot upload limit"
            )
        hasher.update(chunk)
    await upload.seek(0)
    return hasher.hexdigest()


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


async def _surface_matches(
    *,
    db: AsyncSession,
    service: AutopilotPrototypeService,
    user: User,
    project_id: Optional[UUID],
    surface_key: str,
) -> tuple[list[AutopilotJob], list[dict]]:
    """Find active versions in Postgres, falling back to local manifests."""
    records: list[AutopilotJob] = []
    try:
        query = select(AutopilotJob).where(
            AutopilotJob.owner_id == user.id,
            or_(AutopilotJob.surface_key == surface_key, AutopilotJob.surface_key == ""),
            AutopilotJob.status != "superseded",
        )
        if project_id is not None:
            query = query.outerjoin(UploadedAsset, AutopilotJob.repository_asset_id == UploadedAsset.id).where(
                or_(AutopilotJob.project_id == project_id, UploadedAsset.project_id == project_id)
            )
        candidates = list((await db.scalars(query.order_by(AutopilotJob.created_at.desc()))).all())
        records = [record for record in candidates if _record_surface_key(record)[3] == surface_key]
    except Exception as exc:  # pragma: no cover - exercised by degraded storage
        try:
            await db.rollback()
        except Exception:
            pass
        logger.info("Autopilot surface lookup fell back to local manifests: %s", exc)
    if records:
        return records, []
    local = await service.list_local_jobs(str(user.id), str(project_id) if project_id else None)
    return [], [
        job for job in local
        if _local_surface_key(job)[3] == surface_key and job.get("status") != "superseded"
    ]


async def _guard_surface(
    *,
    db: AsyncSession,
    service: AutopilotPrototypeService,
    user: User,
    project_id: Optional[UUID],
    profile_id: str,
    target_kind: str,
    target_url: str | None,
    artifact_sha256: str | None,
    filename: str | None,
    surface_action: str,
) -> tuple[str, str, str, int]:
    """Require an explicit choice when a profile/target/build already exists."""
    canonical_profile, identity, key = _surface_details(
        profile_id,
        target_kind,
        target_url=target_url,
        artifact_sha256=artifact_sha256,
        filename=filename,
    )
    db_records, local_jobs = await _surface_matches(
        db=db, service=service, user=user, project_id=project_id, surface_key=key
    )
    match_count = len(db_records) + len(local_jobs)
    next_version = 1
    if db_records:
        next_version = max(int(getattr(record, "surface_version", 1) or 1) for record in db_records) + 1
    elif local_jobs:
        next_version = max(int(job.get("surface_version") or 1) for job in local_jobs) + 1
    if match_count and surface_action not in {"new", "override"}:
        latest = db_records[0] if db_records else local_jobs[0]
        latest_job_id = latest.job_id if db_records else str(latest.get("job_id"))
        latest_created = latest.created_at.isoformat() if db_records else str(latest.get("created_at", ""))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_surface",
                "message": (
                    "A Test & Audit Report already exists for this profile, target and build/URL. "
                    "Choose whether to keep it and create a new report tab, or override the existing tab."
                ),
                "surface_key": key,
                "surface_identity": identity,
                "existing_job_id": latest_job_id,
                "existing_created_at": latest_created,
                "actions": ["new", "override"],
            },
        )
    if match_count and surface_action == "override":
        try:
            for record in db_records:
                record.status = "superseded"
                record.stage = "superseded"
                record.error = "Superseded by a newer run for the same Autopilot surface."
            if db_records:
                await db.commit()
        except Exception as exc:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The previous Autopilot result could not be superseded; retry after storage recovers.",
            ) from exc
        # Keep the same state in the local manifest when this instance still
        # has one. ``load_job`` prefers that manifest for fast polling.
        for record in db_records:
            try:
                await service.update_job(
                    str(record.job_id),
                    status="superseded",
                    stage="superseded",
                    error="Superseded by a newer run for the same Autopilot surface.",
                )
            except (FileNotFoundError, ValueError):
                pass
        for job in local_jobs:
            try:
                await service.update_job(
                    str(job["job_id"]),
                    status="superseded",
                    stage="superseded",
                    error="Superseded by a newer run for the same Autopilot surface.",
                )
            except Exception:
                logger.info("Could not mark local Autopilot job superseded: %s", job.get("job_id"))
    return canonical_profile, identity, key, next_version


async def _active_project(
    db: AsyncSession,
    user: User,
    header_project_id: Optional[str],
    settings: Settings,
) -> Optional[UUID]:
    if not header_project_id:
        return None
    try:
        project_id = UUID(header_project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project context") from exc
    try:
        if await ProjectRepository(db).get_for_owner(project_id, user.id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - exercised by an unavailable provider
        try:
            await db.rollback()
        except Exception:
            pass
        if settings.AUTOPILOT_DEGRADED_MODE_ENABLED:
            logger.warning("Project context validation skipped in degraded mode: %s", exc)
            return None
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Project storage is temporarily unavailable; check the database plan/quota and retry.",
        ) from exc
    return project_id


async def _require_owned_job(service: AutopilotPrototypeService, job_id: str, user: User):
    try:
        job = await service.load_job(job_id)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autopilot job not found")
    if job.get("owner_id") != str(user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autopilot job not found")
    return job


async def _job_record(db: AsyncSession, job_id: str, owner_id: UUID) -> Optional[AutopilotJob]:
    return await db.scalar(
        select(AutopilotJob).where(
            AutopilotJob.job_id == job_id,
            AutopilotJob.owner_id == owner_id,
        )
    )


async def _safe_job_record(db: AsyncSession, job_id: str, owner_id: UUID) -> Optional[AutopilotJob]:
    """Read the durable job when available without breaking local fallback paths."""
    try:
        return await _job_record(db, job_id, owner_id)
    except Exception as exc:  # pragma: no cover - exercised by unavailable production DBs
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning("Autopilot durable job read skipped: %s", exc)
        return None


async def _link_repository_asset(
    db: AsyncSession,
    service: AutopilotPrototypeService,
    job_id: str,
    asset_id: UUID,
) -> None:
    await service.update_job(job_id, repository_asset_id=str(asset_id))
    try:
        record = await db.scalar(select(AutopilotJob).where(AutopilotJob.job_id == job_id))
        if record is not None:
            record.repository_asset_id = asset_id
            await db.commit()
    except Exception as exc:  # pragma: no cover - degraded DB fallback
        try:
            await db.rollback()
        except Exception:
            pass
        logger.warning("Autopilot repository link write skipped: %s", exc)


async def _ensure_local_artifact(
    db: AsyncSession,
    service: AutopilotPrototypeService,
    job_id: str,
    user: User,
) -> Path:
    # R2 materialization releases the database session with a rollback before
    # copying a large object. Rollback expires ORM instances, so keep the
    # immutable owner id and never read ``user.id`` after that await.
    owner_id = user.id
    job = await _require_owned_job(service, job_id, user)
    if str(job.get("target_kind") or "android") == "web":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Website jobs do not have a mobile artifact.")
    path_value = job.get("apk_path")
    if path_value and Path(path_value).is_file():
        return Path(path_value)

    record = await _safe_job_record(db, job_id, owner_id)
    # The local manifest is deliberately the first durable fallback after a
    # Render restart.  Older rows can have the repository link in that
    # manifest even when the ORM row is briefly unavailable or was written by
    # an earlier deployment, so accept either source after ownership has been
    # verified by ``_require_owned_job`` above.
    asset_id = record.repository_asset_id if record is not None else None
    if asset_id is None:
        raw_asset_id = job.get("repository_asset_id")
        if raw_asset_id and _is_uuid(raw_asset_id):
            asset_id = UUID(str(raw_asset_id))
    if asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The original mobile artifact predates the Upload Repository and is no longer available. "
                "Upload it once more; future runs can reuse it from Test Data → Uploads."
            ),
        )

    target = service.root / job_id / Path(job.get("filename") or "application.apk").name
    try:
        await UploadRepositoryService.materialize(db, asset_id, owner_id, target, settings=service.settings)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored APK was not found")
    await service.update_job(job_id, apk_path=str(target))
    return target


async def _mark_repository_available(
    db: AsyncSession,
    result: AutopilotJobStatus,
    owner_id: UUID,
) -> AutopilotJobStatus:
    if result.artifact_available:
        return result
    record = await _safe_job_record(db, result.job_id, owner_id)
    if record is not None and record.repository_asset_id is not None:
        result.artifact_available = True
    return result


def _record_discovery(record: Optional[AutopilotJob]):
    """Validate a stored Runtime Discovery result before using it for IR."""
    if record is None or record.discovery is None:
        return None
    try:
        return AutopilotDiscoveryResult.model_validate(record.discovery)
    except Exception:
        return None


async def _available_evidence_asset_ids(
    db: AsyncSession,
    user: User,
    record: Optional[AutopilotJob],
    asset_ids: set[UUID],
) -> set[UUID]:
    """Return evidence assets that can still be downloaded in this project.

    Retention and older deployments may leave an evidence UUID in a JSON
    snapshot after its upload row was removed.  Validate references at the
    read boundary so a stale report cannot cause a cascade of 404 requests in
    the browser.  The ownership and project predicates also preserve the same
    isolation enforced by ``GET /uploads/{id}/content``.
    """
    if not asset_ids:
        return set()
    query = select(UploadedAsset.id).where(
        UploadedAsset.id.in_(asset_ids),
        UploadedAsset.owner_id == user.id,
        UploadedAsset.status == "ready",
    )
    if record is not None and record.project_id is not None:
        query = query.where(UploadedAsset.project_id == record.project_id)
    try:
        return set((await db.scalars(query)).all())
    except Exception:
        # Evidence is supplementary.  A degraded database must not turn an
        # otherwise readable analysis into a 500; leave the original payload
        # for the caller's normal fallback handling.
        logger.info("Autopilot evidence availability check skipped", exc_info=True)
        return asset_ids


async def _sanitize_discovery_assets(
    db: AsyncSession,
    user: User,
    record: Optional[AutopilotJob],
    discovery: Optional[AutopilotDiscoveryResult],
) -> Optional[AutopilotDiscoveryResult]:
    """Remove stale screenshot/page-source IDs from a discovery response."""
    if discovery is None:
        return None
    asset_ids = {
        asset_id
        for screen in discovery.screens
        for asset_id in (screen.screenshot_asset_id, screen.page_source_asset_id)
        if asset_id is not None
    }
    available = await _available_evidence_asset_ids(db, user, record, asset_ids)
    changed = False
    screens = []
    for screen in discovery.screens:
        screenshot_asset_id = screen.screenshot_asset_id
        page_source_asset_id = screen.page_source_asset_id
        if screenshot_asset_id is not None and screenshot_asset_id not in available:
            screenshot_asset_id = None
            changed = True
        if page_source_asset_id is not None and page_source_asset_id not in available:
            page_source_asset_id = None
            changed = True
        screens.append(screen.model_copy(update={
            "screenshot_asset_id": screenshot_asset_id,
            "page_source_asset_id": page_source_asset_id,
        }))
    return discovery.model_copy(update={"screens": screens}) if changed else discovery


def _setup_profile(
    job_id: str,
    value: Optional[dict],
    analysis: Optional[AutopilotAnalysis] = None,
    discovery: Optional[AutopilotDiscoveryResult] = None,
) -> AutopilotSetupProfile:
    """Normalize setup references and expose safe input-decision metadata.

    Raw input values are deliberately absent here.  They live only as
    encrypted records managed by ``autopilot_input_store``; this JSON snapshot
    contains decisions and masked metadata so it is safe to copy on reruns.
    """
    raw = dict(value or {})
    raw["job_id"] = job_id
    raw.setdefault("updated_at", None)
    raw.setdefault("input_decisions", {})
    raw.setdefault("saved_inputs", [])
    raw.setdefault("skipped_input_keys", [])
    raw.setdefault("random_input_keys", [])
    raw.pop("input_submissions", None)
    reference_fields = (
        "credential_reference",
        "account_role",
        "environment_name",
        "environment_url",
        "test_data_reference",
        "reset_hook_reference",
        "acceptance_criteria_reference",
        "api_oracle_reference",
        "navigation_notes",
    )
    provided = [name for name in reference_fields if str(raw.get(name) or "").strip()]
    approval_decision = (raw.get("input_decisions") or {}).get("safe_authentication_approved")
    if raw.get("safe_authentication_approved") or approval_decision in {"provide", "reuse"}:
        provided.append("safe_authentication_approved")
    if raw.get("approved_test_ids"):
        provided.append("approved_test_ids")
    if raw.get("runtime_input_references"):
        provided.append("runtime_input_references")
    raw["provided_fields"] = provided
    if analysis is not None:
        normalized_setup = AutopilotSetupProfile.model_validate({**raw, "job_id": job_id})
        requests = build_input_requests(analysis, normalized_setup)
        decisions = normalized_setup.input_decisions or {}
        normalized_requests = []
        for item in requests:
            decision = decisions.get(item.key)
            if decision == "skip":
                item = item.model_copy(update={"status": "skipped", "reference_present": False})
            elif decision in {"provide", "reuse", "random"}:
                item = item.model_copy(update={"status": "random" if decision == "random" else "provided", "reference_present": True})
            normalized_requests.append(item)
        raw["input_requests"] = [item.model_dump(mode="json") for item in normalized_requests]
        raw["missing_fields"] = [item.label for item in normalized_requests if item.status == "pending"]
        runtime_requests = []
        if discovery is not None:
            # Rebuild field-level requests from the current screen map so a
            # discovery captured by an older deployment receives the current
            # direct-input labels, password/OTP hints and safe actions.
            discovered_requests = AutopilotDiscoveryService.runtime_input_requests(discovery.screens)
            source_requests = discovered_requests or list(discovery.input_requests)
            accepted_decisions = {"provide", "reuse", "random"}
            category_provided = {
                # Keep runtime username/password prompts aligned with the
                # plan-level checkpoint.  A legacy generic credential
                # decision must not make live sign-in fields disappear.
                "credential": credential_value_available(normalized_setup)
                or any(
                    decisions.get(item.key) in accepted_decisions
                    for item in source_requests
                    if item.category == "credential" and not item.credential_bundle
                ),
                "test_data": bool(normalized_setup.test_data_reference.strip())
                or any(
                    decisions.get(item.key) in accepted_decisions
                    for item in source_requests
                    if item.category == "test_data"
                ),
            }
            for item in source_requests:
                reference_present = bool(
                    str(normalized_setup.runtime_input_references.get(item.key) or "").strip()
                    or category_provided.get(item.category, False)
                    or decisions.get(item.key) in {"provide", "reuse", "random"}
                )
                decision = decisions.get(item.key)
                runtime_requests.append(
                    item.model_copy(
                        update={
                            "reference_present": reference_present,
                            "status": "skipped" if decision == "skip" else "random" if decision == "random" else "provided" if reference_present else "pending",
                        }
                    )
                )
        elif raw.get("runtime_input_requests"):
            runtime_requests = list(normalized_setup.runtime_input_requests)
        raw["runtime_input_requests"] = [item.model_dump(mode="json") for item in runtime_requests]
        pending_requests = [item for item in normalized_requests if item.status == "pending"]
        pending_runtime_requests = [item for item in runtime_requests if item.status == "pending"]
        # ``missing_fields`` drives the compact dashboard badge as well as the
        # checkpoint dialog. Include field-level requests discovered at
        # runtime; otherwise a post-discovery sign-in/address prompt can be
        # present in the API response but appear as if setup were complete.
        raw["missing_fields"] = [
            *[item.label for item in pending_requests],
            *[item.label for item in pending_runtime_requests],
        ]
        if pending_requests or pending_runtime_requests:
            raw["checkpoint_stage"] = "input_collection"
            raw["checkpoint_message"] = (
                "Choose Enter, Skip, Reuse or Random for each checkpoint input before dependent cases continue."
            )
        elif normalized_requests and any(item.status == "skipped" for item in normalized_requests):
            raw["checkpoint_stage"] = "ready"
            raw["checkpoint_message"] = "Skipped inputs remain blocked; safe, independent checks can continue."
        elif discovery is None or not discovery.screens:
            raw["checkpoint_stage"] = "runtime_discovery"
            raw["checkpoint_message"] = (
                "Setup references are complete. Run Runtime Discovery to map screens and controls before semantic execution."
            )
        else:
            raw["checkpoint_stage"] = "ready"
            raw["checkpoint_message"] = "Setup and runtime discovery are available for safe execution."
    else:
        raw.setdefault("missing_fields", [])
        raw.setdefault("input_requests", [])
        raw.setdefault("runtime_input_requests", [])
        raw.setdefault("checkpoint_stage", "input_collection")
    return AutopilotSetupProfile.model_validate(raw)


def _record_setup(
    record: Optional[AutopilotJob],
    job_id: str,
    analysis: Optional[AutopilotAnalysis] = None,
    discovery: Optional[AutopilotDiscoveryResult] = None,
) -> AutopilotSetupProfile:
    if record is None:
        return _setup_profile(job_id, None, analysis, discovery)
    try:
        return _setup_profile(job_id, record.setup_profile, analysis, discovery)
    except Exception:
        return _setup_profile(job_id, None, analysis, discovery)


async def _setup_with_input_metadata(
    db: AsyncSession,
    record: Optional[AutopilotJob],
    job_id: str,
    analysis: Optional[AutopilotAnalysis] = None,
    discovery: Optional[AutopilotDiscoveryResult] = None,
) -> AutopilotSetupProfile:
    """Build setup from the durable profile and encrypted-input metadata.

    The setup JSON is a safe cache, while ``AutopilotInputRecord`` is the
    source of truth for direct values and their decisions.  Keeping this merge
    in one helper prevents the setup dialog, automation compiler and resume
    endpoint from disagreeing after a prior tab, deploy or partial save.
    """
    profile = _record_setup(record, job_id, analysis, discovery)
    if record is None:
        return profile
    try:
        metadata = await list_metadata(
            db,
            record.owner_id,
            record.project_id,
            (record.surface_key or job_id)[:128],
        )
    except Exception:
        # A degraded database must not hide the safe setup snapshot. The
        # caller can still retry once storage recovers.
        logger.info("Autopilot input metadata merge skipped job_id=%s", job_id, exc_info=True)
        return profile

    # A previous checkpoint version called the credential field a generic
    # "credential-set reference" and allowed a placeholder/reference to be
    # marked as complete.  Keep those rows for audit history, but do not feed
    # them back into the active setup: the current flow must explicitly show
    # the UAT User ID/email + Password fields (or a freshly supplied vault
    # reference) before authenticated cases can continue.
    current_credential_label = "UAT sign-in credentials"
    active_metadata = [
        item
        for item in metadata
        if not (
            item.key == "credential_reference"
            and not str(profile.credential_reference or "").strip()
            and str(item.label or "").strip().casefold() != current_credential_label.casefold()
        )
    ]
    raw = profile.model_dump(mode="json")
    raw["saved_inputs"] = [item.model_dump(mode="json") for item in active_metadata]
    decisions = dict(raw.get("input_decisions") or {})
    request_keys = {
        item.key
        for item in [*(profile.input_requests or []), *(profile.runtime_input_requests or [])]
    }
    # Expired/deleted encrypted rows must not leave a stale ``provide`` or
    # ``reuse`` decision that falsely marks a required field as complete.
    for key in request_keys:
        decisions.pop(key, None)
    for item in active_metadata:
        decisions[item.key] = item.decision
    raw["input_decisions"] = decisions
    approval_decision = decisions.get("safe_authentication_approved")
    if approval_decision in {"provide", "reuse"}:
        raw["safe_authentication_approved"] = True
    elif approval_decision == "skip":
        raw["safe_authentication_approved"] = False
    return _setup_profile(job_id, raw, analysis, discovery)


async def _resume_and_discover_background(
    job_id: str,
    owner_id: UUID,
    settings: Settings,
    resume_payload: AutopilotResumeRequest,
) -> None:
    """Resume a validated checkpoint and immediately map the target safely.

    This runs in a background task so the resume endpoint remains responsive.
    A fresh database session is deliberately used because the request-scoped
    session is closed before BackgroundTasks execute. The same helper is used
    for web and mobile targets and persists discovery plus the updated,
    field-level checkpoint when it completes.
    """
    service = _service(settings)
    try:
        await _prepare_resume_target(settings, job_id, owner_id)
        await service.resume_analysis(job_id)
        current = await service.get_job_status(job_id)
        if current.status != "analyzed":
            logger.info(
                "Autopilot chained discovery skipped job_id=%s status=%s",
                job_id,
                current.status,
            )
            return
        await service.update_job(
            job_id,
            stage="runtime_discovery",
            checkpoint_stage="runtime_discovery",
            checkpoint_message="Setup references validated. Runtime Discovery is mapping safe screens and controls.",
            error=None,
        )
        async with AsyncSessionLocal() as db:
            user = await db.scalar(select(User).where(User.id == owner_id))
            if user is None:
                logger.warning("Autopilot chained discovery owner was not found job_id=%s", job_id)
                return
            job = await _require_owned_job(service, job_id, user)
            target_kind = str(job.get("target_kind") or "android")
            provider = resume_payload.discovery_provider
            if target_kind == "web":
                provider = "playwright"
            elif provider is None:
                provider = "browserstack" if settings.browserstack_configured else "appium"
            request = AutopilotDiscoveryRequest(
                target_kind=target_kind,
                target_url=job.get("target_url"),
                provider=provider,
                appium_url=resume_payload.discovery_appium_url,
                appium_app=resume_payload.discovery_appium_app,
                device_name=resume_payload.discovery_device_name or "Google Pixel 8",
                platform_version=resume_payload.discovery_platform_version or "14.0",
                observe_only=False,
                max_screens=12,
                max_actions=10,
            )
            if target_kind == "web":
                result = await AutopilotWebService(settings, service).discover(job_id, request)
            else:
                await _ensure_local_artifact(db, service, job_id, user)
                result = await AutopilotDiscoveryService(settings, service).run(job_id, request)
            record = await _safe_job_record(db, job_id, user.id)
            if record is not None:
                repository_asset_id = record.repository_asset_id
                for screen in result.screens:
                    screen.screenshot_asset_id = await _persist_evidence_asset(
                        db,
                        user,
                        record,
                        settings,
                        screen.screenshot_path,
                        filename=f"discovery-{job_id[:8]}-{screen.screen_id}.png",
                        content_type="image/png",
                        repository_asset_id=repository_asset_id,
                    )
                    screen.page_source_asset_id = await _persist_evidence_asset(
                        db,
                        user,
                        record,
                        settings,
                        screen.page_source_path,
                        filename=f"discovery-{job_id[:8]}-{screen.screen_id}.{'html' if result.target_kind == 'web' else 'xml'}",
                        content_type="text/html" if result.target_kind == "web" else "application/xml",
                        repository_asset_id=repository_asset_id,
                    )
                record = await _safe_job_record(db, job_id, user.id)
                if record is not None:
                    record.discovery = result.model_dump(mode="json")
                    try:
                        analysis = await service.load_analysis(job_id)
                        record.setup_profile = _setup_profile(
                            job_id,
                            record.setup_profile,
                            analysis,
                            result,
                        ).model_dump(mode="json")
                    except FileNotFoundError:
                        pass
                    await db.commit()
            job_changes: dict[str, object] = {"discovery": result.model_dump(mode="json")}
            if record is not None and getattr(record, "setup_profile", None) is not None:
                job_changes["setup_profile"] = record.setup_profile
            await service.update_job(
                job_id,
                **job_changes,
                stage="ready_for_execution" if result.screens else "runtime_discovery",
                checkpoint_stage="ready" if result.screens else "runtime_discovery",
                checkpoint_message=(
                    "Runtime Discovery completed. Review the discovered map and run safe execution."
                    if result.screens
                    else "Runtime Discovery did not expose an interactive screen; review the captured evidence and retry."
                ),
            )
            logger.info(
                "Autopilot chained discovery finished job_id=%s status=%s screens=%s inputs=%s",
                job_id,
                result.status,
                result.screen_count,
                len(result.input_requests),
            )
    except Exception as exc:  # pragma: no cover - provider-specific background path
        logger.exception("Autopilot chained resume/discovery failed job_id=%s", job_id)
        try:
            await service.update_job(
                job_id,
                stage="runtime_discovery",
                checkpoint_stage="runtime_discovery",
                checkpoint_message="Runtime Discovery could not complete; review the error and retry safely.",
                error=f"{type(exc).__name__}: {str(exc)[:800]}",
            )
        except Exception:
            logger.exception("Autopilot chained discovery failure could not be recorded job_id=%s", job_id)


async def _start_analysis_from_asset(
    *,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    settings: Settings,
    user: User,
    asset: UploadedAsset,
    context: Optional[str],
    profile_id: str = "uae_fintech",
    project_id: Optional[UUID] = None,
    document_asset_ids: Optional[list[UUID]] = None,
    document_analysis_run_id: Optional[UUID] = None,
    canonical_profile_id: str = "uae_fintech",
    surface_key: str = "",
    surface_identity: str = "",
    surface_version: int = 1,
    setup_profile: Optional[dict] = None,
) -> AutopilotJobStatus:
    """Create an analysis job from a durable repository APK or IPA.

    Return the queued job before materializing the file. The repository asset
    remains the source of truth and can be used again after a Render restart;
    the worker copies it into its disposable working directory in the
    background.
    """
    service = _service(settings)
    job_id, _ = await service.save_reused_asset_job(
        asset.filename,
        str(user.id),
        asset.id,
        context=_effective_context(
            context,
            profile_id,
            target_kind="ios" if asset.extension == "ipa" else "android",
            application_name=asset.filename.rsplit(".", 1)[0],
        ),
        target_kind="ios" if asset.extension == "ipa" else "android",
        project_id=str(project_id or asset.project_id) if (project_id or asset.project_id) else None,
        document_asset_ids=[str(value) for value in (document_asset_ids or [])],
        document_analysis_run_id=str(document_analysis_run_id) if document_analysis_run_id else None,
        profile_id=canonical_profile_id,
        surface_key=surface_key,
        surface_identity=surface_identity,
        surface_version=surface_version,
    )

    await _link_repository_asset(db, service, job_id, asset.id)
    if setup_profile:
        await service.update_job(job_id, setup_profile=setup_profile)
    _queue_repository_materialization(background_tasks, settings, job_id, asset.id, user.id)
    result = await service.get_job_status(job_id)
    return await _mark_repository_available(db, result, user.id)


async def _start_analysis_from_local_path(
    *,
    background_tasks: BackgroundTasks,
    settings: Settings,
    user: User,
    source_path: Path,
    filename: str,
    context: Optional[str],
    profile_id: str = "uae_fintech",
    project_id: Optional[UUID] = None,
    document_asset_ids: Optional[list[UUID]] = None,
    document_analysis_run_id: Optional[UUID] = None,
    canonical_profile_id: str = "uae_fintech",
    surface_key: str = "",
    surface_identity: str = "",
    surface_version: int = 1,
    setup_profile: Optional[dict] = None,
) -> AutopilotJobStatus:
    """Rerun a same-instance job while the durable database is unavailable."""
    if not source_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previous APK is not available on this instance. Upload the build again before rerunning it.",
        )
    service = _service(settings)
    reader = _AsyncPathReader(source_path)
    try:
        job_id, _ = await service.save_upload_stream(
            filename,
            reader,
            str(user.id),
            context=_effective_context(
                context,
                profile_id,
                target_kind="ios" if filename.lower().endswith(".ipa") else "android",
                application_name=Path(filename).stem,
            ),
            max_bytes=settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024,
            target_kind="ios" if filename.lower().endswith(".ipa") else "android",
            project_id=str(project_id) if project_id else None,
            document_asset_ids=[str(value) for value in (document_asset_ids or [])],
            document_analysis_run_id=str(document_analysis_run_id) if document_analysis_run_id else None,
            profile_id=canonical_profile_id,
            surface_key=surface_key,
            surface_identity=surface_identity,
            surface_version=surface_version,
        )
    finally:
        await reader.close()
    if setup_profile:
        await service.update_job(job_id, setup_profile=setup_profile)
    background_tasks.add_task(service.analyze_safely, job_id)
    return await service.get_job_status(job_id)


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _persist_evidence_asset(
    db: AsyncSession,
    user: User,
    job_record: AutopilotJob,
    settings: Settings,
    path_value: Optional[str],
    *,
    filename: str,
    content_type: str,
    repository_asset_id: Optional[UUID] = None,
) -> Optional[UUID]:
    """Copy small smoke evidence files into the durable Upload Repository.

    Evidence is best-effort: a storage outage must never turn a completed
    device run into an HTTP 500.  Snapshot the repository asset id before any
    database rollback so the second evidence file and execution row can still
    be persisted when the object store rejects an upload.
    """
    if not path_value:
        return None
    # Evidence persistence may roll back on a storage failure. Snapshot the
    # scalar owner id so fallback paths cannot trigger an implicit ORM refresh
    # (which raises MissingGreenlet in async background work).
    owner_id = user.id
    path = Path(path_value)
    if not path.is_file():
        return None
    project_id = None
    try:
        resolved_repository_asset_id = repository_asset_id
        if resolved_repository_asset_id is None:
            try:
                resolved_repository_asset_id = job_record.repository_asset_id
            except Exception as exc:  # pragma: no cover - detached ORM row
                logger.warning("Autopilot evidence metadata unavailable: %s", exc)
                resolved_repository_asset_id = None
        if resolved_repository_asset_id:
            source = await db.scalar(
                select(UploadedAsset).where(UploadedAsset.id == resolved_repository_asset_id)
            )
            project_id = source.project_id if source is not None else None
        asset = await UploadRepositoryService.create_from_path(
            db,
            path,
            owner_id,
            filename=filename,
            content_type=content_type,
            project_id=project_id,
            source_module="autopilot",
            category="autopilot_evidence",
            max_bytes=25 * 1024 * 1024,
            minimum_bytes=1,
            settings=settings,
        )
        return asset.id
    except Exception as exc:  # pragma: no cover - storage failures are defensive
        try:
            await db.rollback()
        except Exception as rollback_error:  # pragma: no cover - defensive
            logger.warning("Autopilot evidence rollback skipped: %s", rollback_error)
        logger.warning("Autopilot evidence persistence skipped: %s", exc)
        return None


async def _persist_execution(
    service: AutopilotPrototypeService,
    db: AsyncSession,
    user: User,
    job_record: AutopilotJob,
    request: AutopilotExecutionRequest,
    result: AutopilotExecutionResult,
) -> AutopilotExecutionResult:
    """Persist the result and durable evidence references without masking it."""
    execution_id = result.execution_id or uuid4()
    # Rollbacks in evidence persistence expire ORM attributes.  Capture the
    # scalar identifiers before attempting either object-store upload.
    owner_id = user.id
    job_record_id = job_record.id
    repository_asset_id = job_record.repository_asset_id
    screenshot_asset_id = await _persist_evidence_asset(
        db,
        user,
        job_record,
        service.settings,
        result.screenshot_path,
        filename=f"launch-{execution_id}.png",
        content_type="image/png",
        repository_asset_id=repository_asset_id,
    )
    page_source_asset_id = await _persist_evidence_asset(
        db,
        user,
        job_record,
        service.settings,
        result.page_source_path,
        filename=f"page-source-{execution_id}.{'html' if result.target_kind == 'web' else 'xml'}",
        content_type="text/html" if result.target_kind == "web" else "application/xml",
        repository_asset_id=repository_asset_id,
    )
    evidence = dict(result.evidence or {})
    if screenshot_asset_id:
        evidence["screenshot_asset_id"] = str(screenshot_asset_id)
    if page_source_asset_id:
        evidence["page_source_asset_id"] = str(page_source_asset_id)
    result = result.model_copy(
        update={
            "execution_id": execution_id,
            "screenshot_asset_id": screenshot_asset_id,
            "page_source_asset_id": page_source_asset_id,
            "evidence": evidence,
        }
    )
    # Keep the filesystem fallback in sync with evidence IDs in case the
    # database is temporarily unavailable on a later history read.
    await service._persist_execution_file(result, request)
    execution = AutopilotExecution(
        id=execution_id,
        autopilot_job_id=job_record_id,
        owner_id=owner_id,
        repository_asset_id=repository_asset_id,
        provider=request.provider,
        device_name=request.device_name,
        platform_version=request.platform_version,
        appium_url=request.appium_url,
        appium_app=request.appium_app,
        no_reset=request.no_reset,
        auto_grant_permissions=request.auto_grant_permissions,
        status=result.status,
        started_at=_parse_iso_datetime(result.started_at),
        finished_at=_parse_iso_datetime(result.finished_at),
        duration_seconds=result.duration_seconds,
        current_package=result.current_package,
        current_activity=result.current_activity,
        screenshot_asset_id=screenshot_asset_id,
        page_source_asset_id=page_source_asset_id,
        error=result.error,
        evidence=evidence,
    )
    try:
        db.add(execution)
        await db.commit()
    except Exception as exc:  # pragma: no cover - database outage fallback
        await db.rollback()
        logger.warning("Autopilot execution durable write skipped: %s", exc)
    return result


def _execution_record_from_db(row: AutopilotExecution, job_id: str) -> AutopilotExecutionRecord:
    evidence = dict(row.evidence or {})
    if row.screenshot_asset_id:
        evidence.setdefault("screenshot_asset_id", str(row.screenshot_asset_id))
    if row.page_source_asset_id:
        evidence.setdefault("page_source_asset_id", str(row.page_source_asset_id))
    target_kind = str(evidence.get("target_kind") or "android")
    target_url = evidence.get("target_url")
    request = AutopilotExecutionRequest(
        target_kind=target_kind,
        target_url=str(target_url) if target_url else None,
        provider=row.provider,
        appium_url=row.appium_url,
        device_name=row.device_name,
        platform_version=row.platform_version,
        appium_app=row.appium_app,
        no_reset=row.no_reset,
        auto_grant_permissions=row.auto_grant_permissions,
    )
    return AutopilotExecutionRecord(
        execution_id=row.id,
        job_id=job_id,
        status=row.status,
        target_kind=target_kind,
        target_url=str(target_url) if target_url else None,
        provider=row.provider,
        started_at=row.started_at.isoformat(),
        finished_at=row.finished_at.isoformat(),
        duration_seconds=row.duration_seconds,
        device_name=row.device_name,
        current_package=row.current_package,
        current_activity=row.current_activity,
        screenshot_asset_id=row.screenshot_asset_id,
        page_source_asset_id=row.page_source_asset_id,
        error=row.error,
        evidence=evidence,
        request=request,
        created_at=row.created_at,
    )


def _execution_record_from_file(payload: dict, job_id: str) -> Optional[AutopilotExecutionRecord]:
    result = payload.get("result")
    request = payload.get("request")
    if not isinstance(result, dict) or not isinstance(request, dict):
        return None
    try:
        started_at = str(result["started_at"])
        result_payload = dict(result)
        result_payload["execution_id"] = UUID(str(result["execution_id"]))
        result_payload["job_id"] = job_id
        return AutopilotExecutionRecord.model_validate(
            {
                **result_payload,
                "request": AutopilotExecutionRequest.model_validate(request),
                "created_at": _parse_iso_datetime(started_at),
            }
        )
    except (KeyError, TypeError, ValueError):
        return None


async def _execute_and_persist(
    *,
    service: AutopilotPrototypeService,
    db: AsyncSession,
    user: User,
    job_id: str,
    request: AutopilotExecutionRequest,
) -> AutopilotExecutionResult:
    job = await _require_owned_job(service, job_id, user)
    target_kind = str(job.get("target_kind") or "android")
    if target_kind == "web":
        request = request.model_copy(update={
            "target_kind": "web",
            "provider": "playwright",
            "target_url": request.target_url or job.get("target_url"),
        })
    else:
        if request.target_kind != target_kind:
            request = request.model_copy(update={"target_kind": target_kind})
        await _ensure_local_artifact(db, service, job_id, user)
    result = await service.execute_smoke(job_id, request)
    record = await _safe_job_record(db, job_id, user.id)
    if record is not None:
        result = await _persist_execution(service, db, user, record, request, result)
    return result


class _AsyncPathReader:
    def __init__(self, path: Path):
        self._handle = path.open("rb")

    async def read(self, size: int) -> bytes:
        return await asyncio.to_thread(self._handle.read, size)

    async def close(self) -> None:
        await asyncio.to_thread(self._handle.close)


@router.get("/providers", response_model=AutopilotProviderStatus)
async def get_autopilot_providers(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    _ = user
    configured = settings.browserstack_configured
    configured_appium_url = (settings.AUTOPILOT_CUSTOM_APPIUM_URL or "").strip() or None
    if configured_appium_url:
        parsed_appium = urlparse(configured_appium_url)
        if parsed_appium.username or parsed_appium.password:
            # Never echo credentials back to the browser.
            configured_appium_url = None
    custom_available = settings.APP_ENV == "local" or configured_appium_url is not None
    reason = None
    if not custom_available:
        reason = (
            "No reachable Appium endpoint is configured for this hosted service. "
            "Use BrowserStack or set AUTOPILOT_CUSTOM_APPIUM_URL to an authenticated HTTPS endpoint."
        )
    return AutopilotProviderStatus(
        browserstack_configured=configured,
        custom_appium_available=custom_available,
        playwright_available=True,
        custom_appium_reason=reason,
        custom_appium_url=configured_appium_url,
        recommended_provider="browserstack" if configured else "appium",
    )


@router.post("/context/generate", response_model=AutopilotContextResponse)
async def generate_autopilot_context(
    payload: AutopilotContextRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Return the default UAE-fintech profile or an AI-refined context."""
    _ = user
    return await _service(settings).generate_context(payload)


@router.get("/profiles", response_model=list[AutopilotProfileOption])
async def get_autopilot_profiles(
    user: Annotated[User, Depends(get_current_user)],
):
    """Return the selectable profile categories used to seed brief context."""
    _ = user
    return list_profiles()


@router.get("/report-tabs", response_model=list[AutopilotSurface])
@router.get("/surfaces", response_model=list[AutopilotSurface], include_in_schema=False)
async def get_autopilot_report_tabs(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """List retained Test & Audit Report tabs for the active project.

    ``/surfaces`` remains as a hidden compatibility alias for older clients.
    Unlike the original implementation, every non-superseded analysis is
    returned as a tab.  That means an explicit ``new`` choice retains the
    previous report and creates a separately selectable tab; ``override`` is
    the only action that supersedes the previous tab.
    """
    service = _service(settings)
    project_id = await _active_project(db, user, x_qtxpert_project_id, settings)
    records: list[AutopilotJob] = []
    try:
        query = select(AutopilotJob).where(
            AutopilotJob.owner_id == user.id,
            AutopilotJob.status != "superseded",
        )
        if project_id is not None:
            query = query.outerjoin(UploadedAsset, AutopilotJob.repository_asset_id == UploadedAsset.id).where(
                or_(AutopilotJob.project_id == project_id, UploadedAsset.project_id == project_id)
            )
        records = list((await db.scalars(query.order_by(AutopilotJob.created_at.desc()))).all())
    except Exception as exc:  # pragma: no cover - exercised by degraded storage
        try:
            await db.rollback()
        except Exception:
            pass
        logger.info("Autopilot surface list fell back to local manifests: %s", exc)

    rows: list[dict] = []
    if records:
        for record in records:
            profile_id, target_kind, identity, key = _record_surface_key(record)
            rows.append({
                "report_tab_key": build_report_tab_key(
                    key,
                    int(getattr(record, "surface_version", None) or 1),
                    record.job_id,
                ),
                "surface_key": key,
                "surface_identity": identity,
                "profile_id": profile_id,
                "target_kind": target_kind,
                "target_url": record.target_url,
                "filename": record.filename,
                "latest_job_id": record.job_id,
                "latest_status": record.status,
                "latest_created_at": record.created_at.isoformat(),
                "latest_updated_at": record.updated_at.isoformat(),
                "surface_version": int(getattr(record, "surface_version", None) or 1),
            })
    else:
        for job in await service.list_local_jobs(str(user.id), str(project_id) if project_id else None):
            if job.get("status") == "superseded":
                continue
            profile_id, target_kind, identity, key = _local_surface_key(job)
            rows.append({
                "report_tab_key": build_report_tab_key(
                    key,
                    int(job.get("surface_version") or 1),
                    str(job.get("job_id")),
                ),
                "surface_key": key,
                "surface_identity": identity,
                "profile_id": profile_id,
                "target_kind": target_kind,
                "target_url": job.get("target_url"),
                "filename": job.get("filename", ""),
                "latest_job_id": str(job.get("job_id")),
                "latest_status": job.get("status", "uploaded"),
                "latest_created_at": str(job.get("created_at", "")),
                "latest_updated_at": str(job.get("updated_at", job.get("created_at", ""))),
                "surface_version": int(job.get("surface_version") or 1),
            })

    version_counts: dict[str, int] = {}
    for row in rows:
        version_counts[row["surface_key"]] = version_counts.get(row["surface_key"], 0) + 1
    result: list[AutopilotSurface] = []
    for row in rows:
        key = row["surface_key"]
        result.append(
            AutopilotSurface(
                version_count=version_counts.get(key, 1),
                is_current=row["latest_status"] != "superseded",
                **row,
            )
        )
    result.sort(key=lambda item: item.latest_updated_at, reverse=True)
    return result


@router.post("/analyze", response_model=AutopilotJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def analyze_autopilot_target(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: UploadFile | None = File(default=None),
    context: str = Form(default=""),
    profile_id: str = Form(default="uae_fintech"),
    target_url: str = Form(default=""),
    surface_action: str = Form(default="ask"),
    document_asset_ids: str = Form(default=""),
    document_analysis_run_id: str = Form(default=""),
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Analyze a website URL, Android APK or iOS IPA as one Autopilot job."""
    project_id = await _active_project(db, user, x_qtxpert_project_id, settings)
    service = _service(settings)
    if surface_action not in {"ask", "new", "override"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="surface_action must be ask, new or override")
    profile_id = _canonical_profile_id(profile_id)
    selected_document_ids = _parse_document_asset_ids(document_asset_ids)
    baseline_id: UUID | None = None
    if document_analysis_run_id.strip():
        try:
            baseline_id = UUID(document_analysis_run_id.strip())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="document_analysis_run_id is invalid") from exc
    baseline_id, baseline_asset_ids, baseline_context = await _document_analysis_baseline(
        db, user, settings, baseline_id, project_id
    )
    selected_document_ids = _merge_document_asset_ids(baseline_asset_ids, selected_document_ids)
    selected_document_ids, document_excerpt = await _document_context(
        db, user, project_id, selected_document_ids, settings
    )
    normalized_url = target_url.strip()
    inferred_kind = "web" if normalized_url else (
        "ios" if file is not None and str(file.filename or "").lower().endswith(".ipa") else "android"
    )
    analysis_context = _context_with_documents(
        context,
        profile_id,
        document_excerpt,
        target_kind=inferred_kind,
        target_url=normalized_url or None,
        application_name=Path(file.filename).stem if file is not None and file.filename else None,
    )
    if baseline_context:
        analysis_context = f"{baseline_context}\n\n{analysis_context}"[:8000]
    if normalized_url:
        try:
            normalized_url = service.validate_web_url(
                normalized_url,
                allow_private=settings.APP_ENV == "local",
            )
            profile_id, surface_identity, surface_key, surface_version = await _guard_surface(
                db=db,
                service=service,
                user=user,
                project_id=project_id,
                profile_id=profile_id,
                target_kind="web",
                target_url=normalized_url,
                artifact_sha256=None,
                filename=None,
                surface_action=surface_action,
            )
            job_id = await service.save_web_target(
                normalized_url,
                str(user.id),
                context=analysis_context,
                project_id=str(project_id) if project_id else None,
                document_asset_ids=[str(value) for value in selected_document_ids],
                document_analysis_run_id=str(baseline_id) if baseline_id else None,
                profile_id=profile_id,
                surface_key=surface_key,
                surface_identity=surface_identity,
                surface_version=surface_version,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        background_tasks.add_task(service.analyze_safely, job_id)
        result = await service.get_job_status(job_id)
        return await _mark_repository_available(db, result, user.id)

    if file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide a website URL or upload an Android APK/iOS IPA before starting Autopilot.",
        )

    filename = Path(file.filename or "application.apk").name
    extension = Path(filename).suffix.lower()
    if extension not in {".apk", ".ipa"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Autopilot accepts Android .apk and iOS .ipa files, or a website URL.",
        )
    target_kind = "ios" if extension == ".ipa" else "android"
    max_bytes = settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        artifact_sha256 = await _upload_sha256(file, max_bytes=max_bytes)
    except AutopilotUploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    profile_id, surface_identity, surface_key, surface_version = await _guard_surface(
        db=db,
        service=service,
        user=user,
        project_id=project_id,
        profile_id=profile_id,
        target_kind=target_kind,
        target_url=None,
        artifact_sha256=artifact_sha256,
        filename=filename,
        surface_action=surface_action,
    )
    try:
        job_id, apk_path = await service.save_upload_stream(
            filename,
            file,
            str(user.id),
            context=analysis_context,
            max_bytes=max_bytes,
            target_kind=target_kind,
            project_id=str(project_id) if project_id else None,
            document_asset_ids=[str(value) for value in selected_document_ids],
            document_analysis_run_id=str(baseline_id) if baseline_id else None,
            profile_id=profile_id,
            surface_key=surface_key,
            surface_identity=surface_identity,
            surface_version=surface_version,
        )
    except AutopilotUploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    except AutopilotUploadInvalid as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    asset: Optional[UploadedAsset] = None
    if settings.AUTOPILOT_DEGRADED_MODE_ENABLED:
        # The database provider is explicitly unavailable. Keep the APK and
        # all analysis evidence on this instance so the user can complete a
        # smoke run; normal durable repository writes resume when the flag is
        # disabled after the provider quota is restored.
        logger.warning(
            "Autopilot APK repository write bypassed in degraded mode job_id=%s",
            job_id,
        )
    else:
        try:
            asset = await UploadRepositoryService.create_from_path(
                db,
                apk_path,
                user.id,
                filename=filename,
                content_type=file.content_type or ("application/octet-stream" if target_kind == "ios" else "application/vnd.android.package-archive"),
                project_id=project_id,
                source_module="autopilot",
                category=extension.lstrip(".") or "apk",
                max_bytes=max_bytes,
                minimum_bytes=1024,
                settings=settings,
            )
        except UploadRepositoryTooLarge as exc:
            await asyncio.to_thread(shutil.rmtree, service.root / job_id, True)
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
        except UploadRepositoryInvalid as exc:
            await asyncio.to_thread(shutil.rmtree, service.root / job_id, True)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except Exception as exc:
            # PostgreSQL chunk storage can be exhausted by a large APK. Return
            # a useful actionable response instead of leaving the browser
            # waiting for a 500/timeout, and discard only this local job.
            try:
                await db.rollback()
            except Exception:
                pass
            await asyncio.to_thread(shutil.rmtree, service.root / job_id, True)
            logger.exception("Autopilot APK repository write failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail=(
                    "The mobile upload was received but could not be saved to the Upload Repository. "
                    "Increase repository/database capacity or configure object storage, then retry."
                ),
            ) from exc
    if asset is not None:
        await _link_repository_asset(db, service, job_id, asset.id)
    background_tasks.add_task(service.analyze_safely, job_id)
    result = await service.get_job_status(job_id)
    return await _mark_repository_available(db, result, user.id)


@router.post("/analyze-existing", response_model=AutopilotJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def analyze_existing_mobile_app(
    payload: ReuseUploadedAssetRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Start a new mobile analysis from an APK or IPA in the active project."""
    project_id = await _active_project(db, user, x_qtxpert_project_id, settings)
    try:
        asset = await UploadRepositoryService.get_owned(db, payload.upload_id, user.id)
    except Exception as exc:  # pragma: no cover - exercised by an unavailable provider
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored APK reuse is temporarily unavailable; upload the APK file again or restore database access.",
        ) from exc
    if asset is None or asset.extension not in {"apk", "ipa"} or (project_id is not None and asset.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reusable APK/IPA not found in this project")
    max_bytes = settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if asset.size_bytes and asset.size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Stored mobile artifact exceeds the {settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB}MB "
                "Autopilot upload limit. Choose a smaller build or raise the configured limit."
            ),
        )
    canonical_profile, surface_identity, surface_key, surface_version = await _guard_surface(
        db=db,
        service=_service(settings),
        user=user,
        project_id=project_id,
        profile_id=payload.profile_id,
        target_kind="ios" if asset.extension == "ipa" else "android",
        target_url=None,
        artifact_sha256=asset.sha256,
        filename=asset.filename,
        surface_action=payload.surface_action,
    )
    baseline_id, baseline_asset_ids, baseline_context = await _document_analysis_baseline(
        db, user, settings, payload.document_analysis_run_id, project_id
    )
    selected_document_ids = _merge_document_asset_ids(baseline_asset_ids, payload.document_asset_ids)
    selected_document_ids, document_excerpt = await _document_context(
        db, user, project_id, selected_document_ids, settings
    )
    analysis_context = _context_with_documents(
        payload.context,
        canonical_profile,
        document_excerpt,
        target_kind="ios" if asset.extension == "ipa" else "android",
        application_name=asset.filename.rsplit(".", 1)[0],
    )
    if baseline_context:
        analysis_context = f"{baseline_context}\n\n{analysis_context}"[:8000]
    return await _start_analysis_from_asset(
        background_tasks=background_tasks,
        db=db,
        settings=settings,
        user=user,
        asset=asset,
        context=analysis_context,
        profile_id=canonical_profile,
        project_id=project_id,
        document_asset_ids=selected_document_ids,
        document_analysis_run_id=baseline_id,
        canonical_profile_id=canonical_profile,
        surface_key=surface_key,
        surface_identity=surface_identity,
        surface_version=surface_version,
    )


@router.post("/{job_id}/rerun-analysis", response_model=AutopilotJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def rerun_autopilot_analysis(
    job_id: str,
    payload: AutopilotAnalysisRerunRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Create a new analysis from the previous APK or a replacement asset."""
    service = _service(settings)
    original = await _require_owned_job(service, job_id, user)
    original_record = await _safe_job_record(db, job_id, user.id)
    # Reusing setup is opt-in.  The default ``ask`` behaves like a fresh setup
    # for older clients, while the current UI presents the saved references and
    # sends ``reuse`` only after the user confirms them.
    setup_profile_to_copy = (
        dict(original_record.setup_profile)
        if payload.setup_action == "reuse" and original_record is not None and original_record.setup_profile
        else None
    )
    if setup_profile_to_copy is not None:
        # A rerun must never silently carry forward values that the user chose
        # not to save.  Keep only encrypted repository-backed metadata and
        # turn those entries into an explicit ``reuse`` decision; the setup
        # checkpoint will ask for every other input again.
        saved_inputs = [
            item
            for item in (setup_profile_to_copy.get("saved_inputs") or [])
            if isinstance(item, dict) and item.get("save_for_reuse") and item.get("key")
        ]
        saved_keys = {str(item["key"]) for item in saved_inputs}
        setup_profile_to_copy["saved_inputs"] = saved_inputs
        setup_profile_to_copy["input_decisions"] = {
            key: "reuse" for key in saved_keys
        }
        setup_profile_to_copy["skipped_input_keys"] = []
        setup_profile_to_copy["random_input_keys"] = []
    project_id = await _active_project(db, user, x_qtxpert_project_id, settings)
    effective_project_id = project_id or (UUID(str(original["project_id"])) if original.get("project_id") and _is_uuid(original.get("project_id")) else None)
    canonical_profile_id = _canonical_profile_id(payload.profile_id)
    original_target_kind = str(original.get("target_kind") or "android")
    original_document_ids: list[UUID] = []
    for value in original.get("document_asset_ids", []) or []:
        try:
            asset_id = UUID(str(value))
        except (TypeError, ValueError):
            continue
        if asset_id not in original_document_ids:
            original_document_ids.append(asset_id)
    original_baseline_id: UUID | None = None
    raw_baseline_id = original.get("document_analysis_run_id")
    if not raw_baseline_id and original_record is not None:
        raw_baseline_id = getattr(original_record, "document_analysis_run_id", None)
    if raw_baseline_id and _is_uuid(raw_baseline_id):
        original_baseline_id = UUID(str(raw_baseline_id))
    baseline_id = payload.document_analysis_run_id or original_baseline_id
    baseline_id, baseline_asset_ids, baseline_context = await _document_analysis_baseline(
        db, user, settings, baseline_id, effective_project_id
    )
    if payload.document_asset_ids is None:
        selected_document_ids = _merge_document_asset_ids(baseline_asset_ids, original_document_ids)
        selected_document_ids, document_excerpt = await _document_context(
            db, user, effective_project_id, selected_document_ids, settings
        )
        rerun_context = _context_with_documents(
            payload.context if payload.context is not None else _context_without_documents(str(original.get("context", ""))),
            canonical_profile_id,
            document_excerpt,
            target_kind=original_target_kind,
            target_url=original.get("target_url"),
            application_name=Path(str(original.get("filename", ""))).stem or None,
        )
    else:
        selected_document_ids = _merge_document_asset_ids(baseline_asset_ids, payload.document_asset_ids)
        selected_document_ids, document_excerpt = await _document_context(
            db, user, effective_project_id, selected_document_ids, settings
        )
        rerun_context = _context_with_documents(
            payload.context if payload.context is not None else str(original.get("context", "")),
            canonical_profile_id,
            document_excerpt,
            target_kind=original_target_kind,
            target_url=original.get("target_url"),
            application_name=Path(str(original.get("filename", ""))).stem or None,
        )
    if baseline_context:
        rerun_context = f"{baseline_context}\n\n{rerun_context}"[:8000]
    if original_target_kind == "web" and payload.upload_id is None:
        target_url = payload.target_url or str(original.get("target_url") or "")
        try:
            target_url = service.validate_web_url(target_url, allow_private=settings.APP_ENV == "local")
            canonical_profile_id, surface_identity, surface_key, surface_version = await _guard_surface(
                db=db,
                service=service,
                user=user,
                project_id=effective_project_id,
                profile_id=canonical_profile_id,
                target_kind="web",
                target_url=target_url,
                artifact_sha256=None,
                filename=None,
                surface_action=payload.surface_action,
            )
            new_job_id = await service.save_web_target(
                target_url,
                str(user.id),
                context=rerun_context,
                project_id=str(effective_project_id) if effective_project_id else None,
                document_asset_ids=[str(value) for value in selected_document_ids],
                document_analysis_run_id=str(baseline_id) if baseline_id else None,
                profile_id=canonical_profile_id,
                surface_key=surface_key,
                surface_identity=surface_identity,
                surface_version=surface_version,
            )
            if setup_profile_to_copy:
                await service.update_job(new_job_id, setup_profile=setup_profile_to_copy)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        background_tasks.add_task(service.analyze_safely, new_job_id)
        return await service.get_job_status(new_job_id)
    if settings.AUTOPILOT_DEGRADED_MODE_ENABLED and payload.upload_id is None:
        local_sha = str((original.get("analysis") or {}).get("sha256") or "")
        if not local_sha and Path(str(original.get("apk_path", ""))).is_file():
            local_sha = await asyncio.to_thread(_sha256_path, Path(str(original.get("apk_path"))))
        canonical_profile_id, surface_identity, surface_key, surface_version = await _guard_surface(
            db=db,
            service=service,
            user=user,
            project_id=effective_project_id,
            profile_id=canonical_profile_id,
            target_kind=original_target_kind,
            target_url=None,
            artifact_sha256=local_sha,
            filename=Path(str(original.get("filename", "application.apk"))).name,
            surface_action=payload.surface_action,
        )
        return await _start_analysis_from_local_path(
            background_tasks=background_tasks,
            settings=settings,
            user=user,
            source_path=Path(str(original.get("apk_path", ""))),
            filename=Path(str(original.get("filename", "application.apk"))).name,
            context=rerun_context,
            profile_id=canonical_profile_id,
            project_id=effective_project_id,
            document_asset_ids=selected_document_ids,
            document_analysis_run_id=baseline_id,
            canonical_profile_id=canonical_profile_id,
            surface_key=surface_key,
            surface_identity=surface_identity,
            surface_version=surface_version,
            setup_profile=setup_profile_to_copy,
        )
    asset_id = payload.upload_id
    if asset_id is None and original_record is not None:
        asset_id = original_record.repository_asset_id
    if asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis has no reusable APK. Upload the build again before rerunning it.",
        )
    try:
        asset = await UploadRepositoryService.get_owned(db, asset_id, user.id)
    except Exception as exc:  # pragma: no cover - exercised by an unavailable provider
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stored APK reuse is temporarily unavailable; restore database access and retry.",
        ) from exc
    if asset is None or (effective_project_id is not None and asset.project_id != effective_project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reusable APK not found in this project")
    canonical_profile_id, surface_identity, surface_key, surface_version = await _guard_surface(
        db=db,
        service=service,
        user=user,
        project_id=effective_project_id,
        profile_id=canonical_profile_id,
        target_kind="ios" if asset.extension == "ipa" else "android",
        target_url=None,
        artifact_sha256=asset.sha256,
        filename=asset.filename,
        surface_action=payload.surface_action,
    )
    return await _start_analysis_from_asset(
        background_tasks=background_tasks,
        db=db,
        settings=settings,
        user=user,
        asset=asset,
        context=rerun_context,
        profile_id=canonical_profile_id,
        project_id=effective_project_id,
        document_asset_ids=selected_document_ids,
        document_analysis_run_id=baseline_id,
        canonical_profile_id=canonical_profile_id,
        surface_key=surface_key,
        surface_identity=surface_identity,
        surface_version=surface_version,
        setup_profile=setup_profile_to_copy,
    )


@router.get("/jobs/latest", response_model=AutopilotJobStatus | None)
async def get_latest_autopilot_job(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
    surface_key: Optional[str] = Query(default=None, max_length=64),
):
    """Restore the latest Autopilot result for the active project."""
    service = _service(settings)
    project_id = await _active_project(db, user, x_qtxpert_project_id, settings)
    query = select(AutopilotJob).where(
        AutopilotJob.owner_id == user.id,
        AutopilotJob.status != "superseded",
    )
    if surface_key:
        # Include legacy rows whose surface key was added by migration 0019;
        # their profile/target identity is reconstructed below.
        query = query.where(or_(AutopilotJob.surface_key == surface_key, AutopilotJob.surface_key == ""))
    if project_id is not None:
        query = query.outerjoin(UploadedAsset, AutopilotJob.repository_asset_id == UploadedAsset.id).where(
            or_(AutopilotJob.project_id == project_id, UploadedAsset.project_id == project_id)
        )
    try:
        candidates = list((await db.scalars(query.order_by(AutopilotJob.created_at.desc()))).all())
        record = next(
            (item for item in candidates if not surface_key or _record_surface_key(item)[3] == surface_key),
            None,
        )
    except Exception as exc:  # pragma: no cover - exercised by an unavailable provider
        try:
            await db.rollback()
        except Exception:
            pass
        if not settings.AUTOPILOT_DEGRADED_MODE_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Autopilot history is temporarily unavailable; check the database plan/quota and retry.",
            ) from exc
        logger.warning("Autopilot latest-job durable read skipped in degraded mode: %s", exc)
        if surface_key:
            local_jobs = [
                item for item in await service.list_local_jobs(str(user.id), str(project_id) if project_id else None)
                if _local_surface_key(item)[3] == surface_key and item.get("status") != "superseded"
            ]
            return await service.get_job_status(str(local_jobs[0]["job_id"])) if local_jobs else None
        return await service.get_latest_job_status(str(user.id))
    if record is None:
        # The filesystem fallback is owner-wide and therefore only safe when no
        # project context exists (legacy/local clients).
        if surface_key:
            local_jobs = [
                item for item in await service.list_local_jobs(str(user.id), str(project_id) if project_id else None)
                if _local_surface_key(item)[3] == surface_key and item.get("status") != "superseded"
            ]
            return await service.get_job_status(str(local_jobs[0]["job_id"])) if local_jobs else None
        return await service.get_latest_job_status(str(user.id)) if project_id is None else None

    job = await _require_owned_job(service, record.job_id, user)
    local_path = job.get("apk_path")
    if (
        record.status in {"uploaded", "analyzing"}
        and record.target_kind != "web"
        and record.repository_asset_id is not None
        and (not local_path or not Path(local_path).is_file())
    ):
        # Never block a status request on an R2/DB download. This also makes
        # recovery after a Render restart asynchronous for legacy jobs whose
        # queued/materializing marker was only present on the old filesystem.
        _queue_repository_materialization(
            background_tasks,
            settings,
            record.job_id,
            record.repository_asset_id,
            user.id,
        )

    result = await service.get_job_status(record.job_id)
    return await _mark_repository_available(db, result, user.id)


@router.get("/jobs/{job_id}", response_model=AutopilotJobStatus)
async def get_autopilot_job_status(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    service = _service(settings)
    job = await _require_owned_job(service, job_id, user)
    local_path = job.get("apk_path")
    record = await _safe_job_record(db, job_id, user.id)
    if (
        job.get("status") in {"uploaded", "analyzing"}
        and str(job.get("target_kind") or "android") != "web"
        and record is not None
        and record.repository_asset_id is not None
        and (not local_path or not Path(local_path).is_file())
    ):
        _queue_repository_materialization(
            background_tasks,
            settings,
            job_id,
            record.repository_asset_id,
            user.id,
        )

    result = await service.get_job_status(job_id)
    return await _mark_repository_available(db, result, user.id)


@router.get("/{job_id}", response_model=AutopilotAnalysis)
async def get_autopilot_analysis(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    try:
        return await service.load_analysis(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Autopilot analysis is not complete")


@router.get("/{job_id}/automation", response_model=AutopilotAutomationBundle)
async def get_autopilot_automation(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Compile QTX Test IR, consuming durable Runtime Discovery when available."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Autopilot analysis is not complete")
    record = await _safe_job_record(db, job_id, user.id)
    return AutopilotIRCompiler().compile_bundle(
        analysis,
        _record_discovery(record),
        await _setup_with_input_metadata(db, record, job_id, analysis, _record_discovery(record)),
    )


@router.get("/{job_id}/setup", response_model=AutopilotSetupProfile)
async def get_autopilot_setup(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Return only non-secret references used to resolve deferred tests."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    record = await _safe_job_record(db, job_id, user.id)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        analysis = None
    discovery = _record_discovery(record)
    return await _setup_with_input_metadata(db, record, job_id, analysis, discovery)


@router.put("/{job_id}/setup", response_model=AutopilotSetupProfile)
async def update_autopilot_setup(
    job_id: str,
    payload: AutopilotSetupUpdateRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Persist dependency references without accepting passwords, tokens or OTPs."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    reference_fields = (
        "credential_reference",
        "environment_url",
        "test_data_reference",
        "reset_hook_reference",
        "acceptance_criteria_reference",
        "api_oracle_reference",
    )
    normalized_references: dict[str, str] = {}
    secret_markers = ("password=", "passwd=", "token=", "secret=", "bearer ", "otp=")
    for field_name in reference_fields:
        value = str(getattr(payload, field_name, "") or "").strip()
        if any(marker in value.lower() for marker in secret_markers):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enter vault/fixture references only; passwords, tokens and OTPs are not stored here.",
            )
        normalized_references[field_name] = value
    runtime_references: dict[str, str] = {}
    for key, raw_value in (payload.runtime_input_references or {}).items():
        normalized_key = str(key).strip()
        value = str(raw_value or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", normalized_key):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A runtime input reference key is invalid.")
        if len(value) > 500:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A runtime input reference is too long.")
        if any(marker in value.lower() for marker in secret_markers):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Enter vault/fixture references only; passwords, tokens and OTPs are not stored here.",
            )
        if value:
            runtime_references[normalized_key] = value
    if len(runtime_references) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At most 50 runtime input references may be saved per checkpoint.",
        )
    record = await _safe_job_record(db, job_id, user.id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autopilot setup storage is temporarily unavailable.",
        )
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        analysis = None
    discovery = _record_discovery(record)
    current_profile = await _setup_with_input_metadata(db, record, job_id, analysis, discovery)
    request_map = {
        item.key: item
        for item in [*(current_profile.input_requests or []), *(current_profile.runtime_input_requests or [])]
    }
    if payload.input_submissions and not request_map:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Input checkpoints are not available until the analysis has produced its plan.",
        )
    try:
        decisions, saved_inputs = await apply_submissions(
            db,
            settings,
            record,
            payload.input_submissions,
            request_map,
        )
    except AutopilotInputStoreError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stored = payload.model_dump(exclude={"input_submissions"})
    stored.update(normalized_references)
    stored["runtime_input_references"] = runtime_references
    prior_decisions = dict(current_profile.input_decisions or {})
    prior_decisions.update(decisions)
    stored["input_decisions"] = prior_decisions
    # Safe authentication is an explicit boolean checkpoint.  Older clients
    # represented it only as an input decision, so normalize both shapes to
    # the same durable flag before compiling/resuming the analysis.
    approval_decision = prior_decisions.get("safe_authentication_approved")
    if approval_decision in {"provide", "reuse"}:
        stored["safe_authentication_approved"] = True
    elif approval_decision == "skip":
        stored["safe_authentication_approved"] = False
    stored["saved_inputs"] = [item.model_dump(mode="json") for item in saved_inputs]
    stored["skipped_input_keys"] = sorted(key for key, value in prior_decisions.items() if value == "skip")
    stored["random_input_keys"] = sorted(key for key, value in prior_decisions.items() if value == "random")
    stored["updated_at"] = datetime.now(timezone.utc).isoformat()
    profile = _setup_profile(job_id, stored, analysis, discovery)
    try:
        record.setup_profile = profile.model_dump(mode="json")
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.exception("Autopilot setup persistence failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Autopilot setup could not be saved; retry after storage is available.",
        ) from exc
    # Mirror the checkpoint into the job manifest as well as the ORM row.  The
    # manifest makes a same-instance retry immediate; the row is the durable
    # source of truth after a Render restart.
    try:
        await service.update_job(job_id, setup_profile=profile.model_dump(mode="json"))
    except Exception:
        logger.warning("Autopilot setup manifest update skipped job_id=%s", job_id, exc_info=True)
    return profile


@router.post("/{job_id}/resume", response_model=AutopilotJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def resume_autopilot_checkpoint(
    job_id: str,
    payload: AutopilotResumeRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Continue a run only after its checkpoint references are confirmed."""

    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    record = await _safe_job_record(db, job_id, user.id)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError as exc:
        # A Render restart can remove the local analysis snapshot while the
        # uploaded APK remains durable in the repository. Rehydrate the
        # artifact and restart the bounded analysis instead of turning a safe
        # checkpoint confirmation into a failed run.
        recovered_job = await service.load_job(job_id)
        recovered_asset_id = record.repository_asset_id if record is not None else None
        if recovered_asset_id is None:
            raw_asset_id = recovered_job.get("repository_asset_id")
            if raw_asset_id and _is_uuid(raw_asset_id):
                recovered_asset_id = UUID(str(raw_asset_id))
        if recovered_asset_id is not None and str(recovered_job.get("target_kind") or "android") != "web":
            await _ensure_local_artifact(db, service, job_id, user)
            await service.update_job(
                job_id,
                status="uploaded",
                stage="queued",
                progress=5,
                checkpoint_stage="input_collection",
                checkpoint_message="Rehydrating the stored mobile build before validating checkpoint inputs.",
                error=None,
            )
            background_tasks.add_task(service.analyze_safely, job_id)
            return await service.get_job_status(job_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Autopilot analysis is not ready for input validation yet. Re-run analysis from the stored target.",
        ) from exc
    setup = await _setup_with_input_metadata(db, record, job_id, analysis, _record_discovery(record))
    if not payload.confirm_saved_inputs:
        return await service.get_job_status(job_id)
    pending_inputs = [
        item
        for item in [*(setup.input_requests or []), *(setup.runtime_input_requests or [])]
        if item.status == "pending"
    ]
    if pending_inputs:
        current = await service.get_job_status(job_id)
        current.checkpoint_stage = "input_collection"
        current.checkpoint_message = "Choose Enter, Skip, Reuse or Random for each pending input before continuing."
        current.input_requests = pending_inputs
        return current
    await service.update_job(
        job_id,
        status="analyzing",
        stage="validating_inputs",
        progress=85,
        checkpoint_stage="validating_inputs",
        checkpoint_message="Validating approved setup references before continuing.",
        input_requests=[],
        error=None,
    )
    if payload.run_runtime_discovery:
        background_tasks.add_task(
            _resume_and_discover_background,
            job_id,
            user.id,
            settings,
            payload,
        )
    else:
        background_tasks.add_task(
            _resume_analysis_background,
            settings,
            job_id,
            user.id,
        )
    return await service.get_job_status(job_id)


@router.post("/{job_id}/discover", response_model=AutopilotDiscoveryResult)
async def run_autopilot_discovery(
    job_id: str,
    payload: AutopilotDiscoveryRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Perform bounded safe navigation and persist the discovered app map."""
    service = _service(settings)
    job = await _require_owned_job(service, job_id, user)
    target_kind = str(job.get("target_kind") or "android")
    if target_kind == "web":
        web_request = payload.model_copy(update={
            "target_kind": "web",
            "provider": "playwright",
            "target_url": payload.target_url or job.get("target_url"),
        })
        result = await AutopilotWebService(settings, service).discover(job_id, web_request)
    else:
        await _ensure_local_artifact(db, service, job_id, user)
        if target_kind == "ios" and payload.provider == "appium" and not payload.appium_app:
            # A hosted Appium endpoint cannot see a Render-local IPA path. The
            # BrowserStack adapter materializes the repository asset itself;
            # custom remote labs must provide their own reachable app reference.
            record = await _safe_job_record(db, job_id, user.id)
            if settings.APP_ENV != "local" and record is not None and record.repository_asset_id and not payload.appium_app:
                raise HTTPException(status_code=400, detail="Hosted custom Appium requires a remote IPA reference for iOS discovery.")
        result = await AutopilotDiscoveryService(settings, service).run(job_id, payload)
    record = await _safe_job_record(db, job_id, user.id)
    if record is not None and result.screens:
        repository_asset_id = record.repository_asset_id
        for screen in result.screens:
            screen.screenshot_asset_id = await _persist_evidence_asset(
                db,
                user,
                record,
                settings,
                screen.screenshot_path,
                filename=f"discovery-{job_id[:8]}-{screen.screen_id}.png",
                content_type="image/png",
                repository_asset_id=repository_asset_id,
            )
            screen.page_source_asset_id = await _persist_evidence_asset(
                db,
                user,
                record,
                settings,
                screen.page_source_path,
                filename=f"discovery-{job_id[:8]}-{screen.screen_id}.{'html' if result.target_kind == 'web' else 'xml'}",
                content_type="text/html" if result.target_kind == "web" else "application/xml",
                repository_asset_id=repository_asset_id,
            )
        record = await _safe_job_record(db, job_id, user.id)
    if record is not None:
        try:
            record.discovery = result.model_dump(mode="json")
            # Runtime discovery is also the source for field-level setup
            # prompts. Refresh the durable checkpoint immediately so a page
            # refresh (or another worker) sees the same entry points.
            try:
                analysis = await service.load_analysis(job_id)
                profile = await _setup_with_input_metadata(db, record, job_id, analysis, result)
                record.setup_profile = profile.model_dump(mode="json")
            except FileNotFoundError:
                pass
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("Autopilot discovery durable write skipped", exc_info=True)
    try:
        job_changes: dict[str, object] = {"discovery": result.model_dump(mode="json")}
        if record is not None and getattr(record, "setup_profile", None) is not None:
            job_changes["setup_profile"] = record.setup_profile
        await service.update_job(job_id, **job_changes)
    except Exception:
        logger.warning("Autopilot discovery manifest update skipped job_id=%s", job_id, exc_info=True)
    return result


@router.get("/{job_id}/discovery", response_model=AutopilotDiscoveryResult | None)
async def get_autopilot_discovery(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Restore the latest durable runtime discovery result for this job."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    record = await _safe_job_record(db, job_id, user.id)
    return await _sanitize_discovery_assets(db, user, record, _record_discovery(record))


@router.post("/{job_id}/suite", response_model=AutopilotSuiteResult)
async def execute_autopilot_suite(
    job_id: str,
    payload: AutopilotSuiteRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Execute only QTX IR cases proven safe and deterministic."""
    service = _service(settings)
    job = await _require_owned_job(service, job_id, user)
    record = await _safe_job_record(db, job_id, user.id)
    if str(job.get("target_kind") or "android") == "web":
        analysis = await service.load_analysis(job_id)
        discovery = _record_discovery(record)
        setup = await _setup_with_input_metadata(db, record, job_id, analysis, discovery)
        bundle = AutopilotIRCompiler().compile_bundle(analysis, discovery, setup)
        requested_ids = set(payload.test_ids)
        requested_buckets = set(payload.buckets)
        selected = [
            item for item in bundle.tests
            if (not requested_ids or item.test_id in requested_ids)
            and (not requested_buckets or item.bucket in requested_buckets)
        ][: payload.max_tests]
        candidates = [item for item in selected if item.readiness == "executable" and item.steps]
        deferred = [item for item in selected if item not in candidates]
        if not candidates:
            now = datetime.now(timezone.utc).isoformat()
            result = AutopilotSuiteResult(
                job_id=job_id,
                target_kind="web",
                target_url=job.get("target_url"),
                provider="playwright",
                status="blocked",
                started_at=now,
                finished_at=now,
                duration_seconds=0,
                device_name="Chromium (headless)",
                selected_count=len(selected),
                deferred_count=len(deferred),
                skipped_count=len(deferred),
                bucket_counts={item.bucket: sum(candidate.bucket == item.bucket for candidate in selected) for item in selected},
                error="No safe deterministic website checks are available; deferred cases list their dependencies.",
                tests=AutopilotSuiteService._deferred_results(deferred) if payload.include_deferred else [],
            )
        else:
            web_request = payload.model_copy(update={
                "target_kind": "web",
                "provider": "playwright",
                "target_url": payload.target_url or job.get("target_url"),
            })
            result = await AutopilotWebService(settings, service).safe_suite(job_id, web_request, candidates)
            deferred_results = AutopilotSuiteService._deferred_results(deferred) if payload.include_deferred else []
            result = result.model_copy(update={
                "selected_count": len(selected),
                "deferred_count": len(deferred),
                "skipped_count": result.skipped_count + len(deferred_results),
                "tests": result.tests + deferred_results,
            })
    else:
        await _ensure_local_artifact(db, service, job_id, user)
        try:
            analysis_for_setup = await service.load_analysis(job_id)
        except FileNotFoundError:
            analysis_for_setup = None
        discovery = _record_discovery(record)
        result = await AutopilotSuiteService(settings, service).run(
            job_id,
            payload,
            discovery,
            await _setup_with_input_metadata(db, record, job_id, analysis_for_setup, discovery),
        )
    if record is not None:
        try:
            record.suite_execution = result.model_dump(mode="json")
            await db.commit()
        except Exception:
            await db.rollback()
            logger.warning("Autopilot suite durable write skipped", exc_info=True)
    return result


@router.get("/{job_id}/suite", response_model=AutopilotSuiteResult | None)
async def get_autopilot_suite(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Restore the latest durable safe-suite result for this build."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    record = await _safe_job_record(db, job_id, user.id)
    if record is None or record.suite_execution is None:
        return None
    try:
        return AutopilotSuiteResult.model_validate(record.suite_execution)
    except ValueError:
        return None


async def _execution_records_for_job(
    job_id: str,
    user: User,
    settings: Settings,
    db: AsyncSession,
) -> list[AutopilotExecutionRecord]:
    """Load durable execution history with a same-instance fallback."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    job_record = await _safe_job_record(db, job_id, user.id)
    records: list[AutopilotExecutionRecord] = []
    if job_record is not None:
        try:
            rows = await db.scalars(
                select(AutopilotExecution)
                .where(
                    AutopilotExecution.autopilot_job_id == job_record.id,
                    AutopilotExecution.owner_id == user.id,
                )
                .order_by(AutopilotExecution.created_at.desc())
                .limit(50)
            )
            records = [_execution_record_from_db(row, job_id) for row in rows.all()]
        except Exception as exc:  # pragma: no cover - fallback for a degraded DB
            await db.rollback()
            logger.warning("Autopilot execution history read skipped: %s", exc)
    if records:
        return records
    fallback = await service.list_execution_files(job_id)
    for payload in fallback:
        record = _execution_record_from_file(payload, job_id)
        if record is not None:
            records.append(record)
    return records


@router.get("/{job_id}/executions", response_model=list[AutopilotExecutionRecord])
async def list_autopilot_executions(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Return durable smoke history, newest first."""
    return await _execution_records_for_job(job_id, user, settings, db)


@router.get("/{job_id}/report", response_model=AutopilotTestAuditReport)
async def get_autopilot_report(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Build an executive Test and Audit Report from the latest evidence."""
    service = _service(settings)
    job = await _require_owned_job(service, job_id, user)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Autopilot analysis is not complete")

    record = await _safe_job_record(db, job_id, user.id)
    discovery = await _sanitize_discovery_assets(db, user, record, _record_discovery(record))
    suite = None
    if record is not None and record.suite_execution is not None:
        try:
            suite = AutopilotSuiteResult.model_validate(record.suite_execution)
        except ValueError:
            suite = None
    executions = await _execution_records_for_job(job_id, user, settings, db)
    return build_test_audit_report(
        analysis,
        str(job.get("context", "")),
        discovery=discovery,
        suite=suite,
        executions=executions,
    )


async def _remove_local_report_data(
    service: AutopilotPrototypeService,
    job_id: str,
    job: dict,
    *,
    preserve_source: bool,
) -> tuple[bool, bool]:
    """Remove report derivatives without escaping the Autopilot storage root.

    Repository-backed APK/IPA files are disposable materializations, so their
    per-job copy can be removed.  A legacy/degraded job without a repository
    asset keeps its source file while its manifest, analysis and execution
    derivatives are removed.
    """
    try:
        job_dir = service._job_dir(job_id).resolve()
        root = service.root.resolve()
        if job_dir.parent != root or not job_dir.exists():
            return False, False

        source_name = Path(str(job.get("apk_path") or job.get("filename") or "")).name
        if not preserve_source:
            await asyncio.to_thread(shutil.rmtree, job_dir)
            return True, False

        source_preserved = False
        for child in await asyncio.to_thread(lambda: list(job_dir.iterdir())):
            # Keep only the legacy source artifact.  Everything else is report
            # state or generated evidence and is safe to remove.
            if child.is_file() and source_name and child.name == source_name:
                source_preserved = True
                continue
            try:
                if child.is_dir():
                    await asyncio.to_thread(shutil.rmtree, child)
                else:
                    await asyncio.to_thread(child.unlink)
            except OSError:
                logger.warning("Could not remove local Autopilot report path %s", child, exc_info=True)
        try:
            await asyncio.to_thread(job_dir.rmdir)
        except OSError:
            # The source artifact intentionally keeps the directory alive.
            pass
        return True, source_preserved
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning("Local Autopilot report cleanup skipped job_id=%s: %s", job_id, exc)
        return False, False


def _uuid_values(values: object) -> set[UUID]:
    """Extract UUID-shaped repository references from report metadata."""
    if values is None:
        return set()
    if isinstance(values, (list, tuple, set)):
        candidates = values
    else:
        candidates = [values]
    result: set[UUID] = set()
    for value in candidates:
        try:
            result.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return result


@router.delete("/{job_id}/report", response_model=AutopilotReportDeletionResult)
async def delete_autopilot_report(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Delete one Test & Audit Report while preserving repository uploads.

    This endpoint never calls the Upload Repository delete path.  Original
    APK/IPA, documents and captured evidence assets remain reusable; only the
    selected report's job, setup/checkpoint metadata, smoke history and local
    generated derivatives are removed.
    """
    service = _service(settings)
    try:
        job = await _require_owned_job(service, job_id, user)
    except HTTPException:
        raise

    record: AutopilotJob | None = None
    if service._durable_results_enabled:
        try:
            record = await _job_record(db, job_id, user.id)
        except Exception as exc:
            await db.rollback()
            logger.exception("Autopilot report deletion could not read durable job job_id=%s", job_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Report storage is temporarily unavailable; retry the delete after storage recovers.",
            ) from exc

    current_status = str(getattr(record, "status", None) or job.get("status") or "")
    if current_status in {"uploaded", "analyzing"}:
        # A live analysis can still write its manifest/row after a delete. Do
        # not race it; the UI can retry once the run reaches a terminal state.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This report is still running. Wait for analysis to finish before deleting it.",
        )

    preserved_upload_ids = _uuid_values(job.get("repository_asset_id"))
    preserved_upload_ids.update(_uuid_values(job.get("document_asset_ids")))
    execution_rows: list[AutopilotExecution] = []
    deleted = {"autopilot_inputs": 0, "autopilot_executions": 0, "autopilot_job": 0}
    preserved_shared_input_records = 0
    if record is not None:
        preserved_upload_ids.update(_uuid_values(record.repository_asset_id))
        try:
            execution_rows = list(
                (
                    await db.scalars(
                        select(AutopilotExecution).where(
                            AutopilotExecution.autopilot_job_id == record.id,
                            AutopilotExecution.owner_id == user.id,
                        )
                    )
                ).all()
            )
            for execution in execution_rows:
                preserved_upload_ids.update(
                    _uuid_values(
                        [
                            execution.repository_asset_id,
                            execution.screenshot_asset_id,
                            execution.page_source_asset_id,
                        ]
                    )
                )

            # Saved checkpoint values are surface-scoped so a second report
            # version can reuse them. Do not erase those encrypted records when
            # another non-superseded report for the same surface still exists.
            shared_surface_job = None
            if record.surface_key:
                shared_surface_job = await db.scalar(
                    select(AutopilotJob.id)
                    .where(
                        AutopilotJob.owner_id == user.id,
                        AutopilotJob.surface_key == record.surface_key,
                        AutopilotJob.id != record.id,
                        AutopilotJob.status != "superseded",
                    )
                    .limit(1)
                )
            if shared_surface_job is not None:
                input_rows = list(
                    (
                        await db.scalars(
                            select(AutopilotInputRecord.id).where(
                                AutopilotInputRecord.owner_id == user.id,
                                AutopilotInputRecord.job_id == job_id,
                            )
                        )
                    ).all()
                )
                preserved_shared_input_records = len(input_rows)
            else:
                input_result = await db.execute(
                    delete(AutopilotInputRecord).where(
                        AutopilotInputRecord.owner_id == user.id,
                        AutopilotInputRecord.job_id == job_id,
                    )
                )
                deleted["autopilot_inputs"] = max(0, int(input_result.rowcount or 0))
            if execution_rows:
                execution_result = await db.execute(
                    delete(AutopilotExecution).where(
                        AutopilotExecution.id.in_([item.id for item in execution_rows]),
                        AutopilotExecution.owner_id == user.id,
                    )
                )
                deleted["autopilot_executions"] = max(0, int(execution_result.rowcount or 0))
            job_result = await db.execute(
                delete(AutopilotJob).where(
                    AutopilotJob.id == record.id,
                    AutopilotJob.owner_id == user.id,
                )
            )
            deleted["autopilot_job"] = max(0, int(job_result.rowcount or 0))
            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.exception("Autopilot report deletion failed job_id=%s", job_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The report could not be deleted because report storage is temporarily unavailable.",
            ) from exc

    preserve_source = not bool(job.get("repository_asset_id") or getattr(record, "repository_asset_id", None))
    local_removed, local_source_preserved = await _remove_local_report_data(
        service,
        job_id,
        job,
        preserve_source=preserve_source,
    )
    logger.info(
        "Autopilot report deleted job_id=%s owner_id=%s deleted=%s preserved_uploads=%d local_removed=%s",
        job_id,
        user.id,
        deleted,
        len(preserved_upload_ids),
        local_removed,
    )
    return AutopilotReportDeletionResult(
        job_id=job_id,
        deleted=deleted,
        preserved_upload_ids=sorted(preserved_upload_ids, key=str),
        preserved_shared_input_records=preserved_shared_input_records,
        local_report_data_removed=local_removed,
        local_source_preserved=local_source_preserved,
    )


@router.post("/{job_id}/smoke", response_model=AutopilotExecutionResult)
async def execute_autopilot_smoke(
    job_id: str,
    payload: AutopilotExecutionRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Run safe smoke; re-materialize the stored APK if Render has restarted."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    return await _execute_and_persist(
        service=service,
        db=db,
        user=user,
        job_id=job_id,
        request=payload,
    )


@router.post(
    "/{job_id}/executions/{execution_id}/rerun",
    response_model=AutopilotExecutionResult,
)
async def rerun_autopilot_smoke(
    job_id: str,
    execution_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Repeat a previous safe smoke with the exact same target settings."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    job_record = await _safe_job_record(db, job_id, user.id)
    stored = None
    if job_record is not None:
        try:
            stored = await db.scalar(
                select(AutopilotExecution).where(
                    AutopilotExecution.id == execution_id,
                    AutopilotExecution.autopilot_job_id == job_record.id,
                    AutopilotExecution.owner_id == user.id,
                )
            )
        except Exception as exc:  # pragma: no cover - migration/DB outage fallback
            try:
                await db.rollback()
            except Exception:
                pass
            logger.warning("Autopilot execution lookup skipped: %s", exc)

    if stored is not None:
        request = AutopilotExecutionRequest(
            provider=stored.provider,
            appium_url=stored.appium_url,
            device_name=stored.device_name,
            platform_version=stored.platform_version,
            appium_app=stored.appium_app,
            no_reset=stored.no_reset,
            auto_grant_permissions=stored.auto_grant_permissions,
        )
    else:
        # A same-instance run can still be rerun if the database is briefly
        # unavailable or the new table has not been migrated yet.
        fallback = await service.list_execution_files(job_id)
        fallback_record = next(
            (
                _execution_record_from_file(payload, job_id)
                for payload in fallback
                if str(payload.get("execution_id")) == str(execution_id)
            ),
            None,
        )
        if fallback_record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Autopilot execution not found")
        request = fallback_record.request
    return await _execute_and_persist(
        service=service,
        db=db,
        user=user,
        job_id=job_id,
        request=request,
    )

