"""Authenticated API endpoints for the Android-first Autopilot prototype."""
import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.autopilot_execution import AutopilotExecution
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.uploaded_asset import UploadedAsset
from app.database.models.user import User
from app.database.repositories.requirement_repository import ProjectRepository
from app.database.session import get_db_session
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAnalysisRerunRequest,
    AutopilotAutomationBundle,
    AutopilotExecutionRecord,
    AutopilotExecutionRequest,
    AutopilotExecutionResult,
    AutopilotJobStatus,
    AutopilotProviderStatus,
)
from app.schemas.upload_repository import ReuseUploadedAssetRequest
from app.services.autopilot import (
    AutopilotPrototypeService,
    AutopilotUploadInvalid,
    AutopilotUploadTooLarge,
)
from app.services.autopilot_ir import AutopilotIRCompiler
from app.services.upload_repository import UploadRepositoryService

router = APIRouter(prefix="/autopilot", tags=["autopilot"])
logger = logging.getLogger(__name__)


def _service(settings: Settings) -> AutopilotPrototypeService:
    return AutopilotPrototypeService(settings)


async def _active_project(
    db: AsyncSession,
    user: User,
    header_project_id: Optional[str],
) -> Optional[UUID]:
    if not header_project_id:
        return None
    try:
        project_id = UUID(header_project_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid project context") from exc
    if await ProjectRepository(db).get_for_owner(project_id, user.id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
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
    record = await db.scalar(select(AutopilotJob).where(AutopilotJob.job_id == job_id))
    if record is not None:
        record.repository_asset_id = asset_id
        await db.commit()


async def _ensure_local_artifact(
    db: AsyncSession,
    service: AutopilotPrototypeService,
    job_id: str,
    user: User,
) -> Path:
    job = await _require_owned_job(service, job_id, user)
    path_value = job.get("apk_path")
    if path_value and Path(path_value).is_file():
        return Path(path_value)

    record = await _safe_job_record(db, job_id, user.id)
    asset_id = record.repository_asset_id if record is not None else None
    if asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The original APK predates the Upload Repository and is no longer available. "
                "Upload it once more; future runs can reuse it from Test Data → Uploads."
            ),
        )

    target = service.root / job_id / Path(job.get("filename") or "application.apk").name
    try:
        await UploadRepositoryService.materialize(db, asset_id, user.id, target)
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


async def _start_analysis_from_asset(
    *,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
    settings: Settings,
    user: User,
    asset: UploadedAsset,
    context: str,
) -> AutopilotJobStatus:
    """Create an analysis job from a durable repository APK.

    The materialized file is disposable; the repository asset remains the
    source of truth and can be used again after a Render restart.
    """
    service = _service(settings)
    temp_dir = service.root / "_repository_reuse" / f"{asset.id}-{uuid4()}"
    temp_path = temp_dir / Path(asset.filename).name
    await UploadRepositoryService.materialize(db, asset.id, user.id, temp_path)
    reader = _AsyncPathReader(temp_path)
    try:
        job_id, _ = await service.save_upload_stream(
            asset.filename,
            reader,
            str(user.id),
            context=context,
            max_bytes=settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        )
    finally:
        await reader.close()
        await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    await _link_repository_asset(db, service, job_id, asset.id)
    background_tasks.add_task(service.analyze_safely, job_id)
    result = await service.get_job_status(job_id)
    return await _mark_repository_available(db, result, user.id)


def _parse_iso_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _persist_evidence_asset(
    db: AsyncSession,
    user: User,
    job_record: AutopilotJob,
    path_value: Optional[str],
    *,
    filename: str,
    content_type: str,
) -> Optional[UUID]:
    """Copy small smoke evidence files into the durable Upload Repository."""
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        return None
    project_id = None
    if job_record.repository_asset_id:
        source = await db.scalar(
            select(UploadedAsset).where(UploadedAsset.id == job_record.repository_asset_id)
        )
        project_id = source.project_id if source is not None else None
    try:
        asset = await UploadRepositoryService.create_from_path(
            db,
            path,
            user.id,
            filename=filename,
            content_type=content_type,
            project_id=project_id,
            source_module="autopilot",
            category="autopilot_evidence",
            max_bytes=25 * 1024 * 1024,
            minimum_bytes=1,
        )
        return asset.id
    except Exception as exc:  # pragma: no cover - storage failures are defensive
        await db.rollback()
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
    screenshot_asset_id = await _persist_evidence_asset(
        db,
        user,
        job_record,
        result.screenshot_path,
        filename=f"launch-{execution_id}.png",
        content_type="image/png",
    )
    page_source_asset_id = await _persist_evidence_asset(
        db,
        user,
        job_record,
        result.page_source_path,
        filename=f"page-source-{execution_id}.xml",
        content_type="application/xml",
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
        autopilot_job_id=job_record.id,
        owner_id=user.id,
        repository_asset_id=job_record.repository_asset_id,
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
    request = AutopilotExecutionRequest(
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
    return AutopilotProviderStatus(
        browserstack_configured=configured,
        custom_appium_available=True,
        recommended_provider="browserstack" if configured else "appium",
    )


@router.post("/analyze", response_model=AutopilotJobStatus, status_code=status.HTTP_202_ACCEPTED)
async def analyze_mobile_app(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    file: UploadFile = File(...),
    context: str = Form(default=""),
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Upload an APK into the active project's repository, then analyze it."""
    project_id = await _active_project(db, user, x_qtxpert_project_id)
    filename = Path(file.filename or "application.apk").name
    if not filename.lower().endswith(".apk"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current prototype supports Android APK files. IPA support is the next platform milestone.",
        )

    service = _service(settings)
    max_bytes = settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    try:
        job_id, apk_path = await service.save_upload_stream(
            filename,
            file,
            str(user.id),
            context=context,
            max_bytes=max_bytes,
        )
    except AutopilotUploadTooLarge as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    except AutopilotUploadInvalid as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    asset = await UploadRepositoryService.create_from_path(
        db,
        apk_path,
        user.id,
        filename=filename,
        content_type=file.content_type or "application/vnd.android.package-archive",
        project_id=project_id,
        source_module="autopilot",
        category="apk",
        max_bytes=max_bytes,
        minimum_bytes=1024,
    )
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
    """Start a new Android analysis from an APK in the active project."""
    project_id = await _active_project(db, user, x_qtxpert_project_id)
    asset = await UploadRepositoryService.get_owned(db, payload.upload_id, user.id)
    if asset is None or asset.extension != "apk" or (project_id is not None and asset.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reusable APK not found in this project")
    return await _start_analysis_from_asset(
        background_tasks=background_tasks,
        db=db,
        settings=settings,
        user=user,
        asset=asset,
        context=payload.context,
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
    project_id = await _active_project(db, user, x_qtxpert_project_id)
    asset_id = payload.upload_id
    if asset_id is None and original_record is not None:
        asset_id = original_record.repository_asset_id
    if asset_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This analysis has no reusable APK. Upload the build again before rerunning it.",
        )
    asset = await UploadRepositoryService.get_owned(db, asset_id, user.id)
    if asset is None or (project_id is not None and asset.project_id != project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reusable APK not found in this project")
    context = payload.context if payload.context is not None else str(original.get("context", ""))
    return await _start_analysis_from_asset(
        background_tasks=background_tasks,
        db=db,
        settings=settings,
        user=user,
        asset=asset,
        context=context,
    )


@router.get("/jobs/latest", response_model=AutopilotJobStatus | None)
async def get_latest_autopilot_job(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_project_id: Annotated[Optional[str], Header()] = None,
):
    """Restore the latest Autopilot result for the active project."""
    service = _service(settings)
    project_id = await _active_project(db, user, x_qtxpert_project_id)
    query = select(AutopilotJob).where(AutopilotJob.owner_id == user.id)
    if project_id is not None:
        query = query.join(UploadedAsset, AutopilotJob.repository_asset_id == UploadedAsset.id).where(
            UploadedAsset.project_id == project_id
        )
    record = await db.scalar(query.order_by(AutopilotJob.created_at.desc()).limit(1))
    if record is None:
        # The filesystem fallback is owner-wide and therefore only safe when no
        # project context exists (legacy/local clients).
        return await service.get_latest_job_status(str(user.id)) if project_id is None else None

    job = await _require_owned_job(service, record.job_id, user)
    local_path = job.get("apk_path")
    if (
        record.status in {"uploaded", "analyzing"}
        and record.repository_asset_id is not None
        and (not local_path or not Path(local_path).is_file())
    ):
        await _ensure_local_artifact(db, service, record.job_id, user)
        background_tasks.add_task(service.analyze_safely, record.job_id)

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
        and record is not None
        and record.repository_asset_id is not None
        and (not local_path or not Path(local_path).is_file())
    ):
        await _ensure_local_artifact(db, service, job_id, user)
        background_tasks.add_task(service.analyze_safely, job_id)

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
):
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Autopilot analysis is not complete")
    return AutopilotIRCompiler().compile_bundle(analysis)


@router.get("/{job_id}/executions", response_model=list[AutopilotExecutionRecord])
async def list_autopilot_executions(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Return durable smoke history, newest first."""
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
