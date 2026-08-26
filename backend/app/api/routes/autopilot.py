"""Authenticated API endpoints for the Android-first Autopilot prototype."""
import asyncio
import shutil
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.user import User
from app.database.session import get_db_session
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAutomationBundle,
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


def _service(settings: Settings) -> AutopilotPrototypeService:
    return AutopilotPrototypeService(settings)


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


async def _link_repository_asset(
    db: AsyncSession,
    service: AutopilotPrototypeService,
    job_id: str,
    asset_id: UUID,
) -> None:
    # Keep the local job manifest informative for local development.
    await service.update_job(job_id, repository_asset_id=str(asset_id))
    # Deployed Autopilot job metadata is durable in PostgreSQL.
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

    record = await _job_record(db, job_id, user.id)
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
    record = await _job_record(db, result.job_id, owner_id)
    if record is not None and record.repository_asset_id is not None:
        result.artifact_available = True
    return result


class _AsyncPathReader:
    """Small adapter allowing the existing bounded upload writer to reuse a stored APK."""

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
    """Return execution-provider readiness without exposing credentials."""
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
):
    """Upload an APK, save it to the shared repository, then analyze it."""
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

    # Persist the original APK independently of Render's replaceable filesystem.
    asset = await UploadRepositoryService.create_from_path(
        db,
        apk_path,
        user.id,
        filename=filename,
        content_type=file.content_type or "application/vnd.android.package-archive",
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
):
    """Start a new Android analysis from an APK already in Test Data → Uploads."""
    asset = await UploadRepositoryService.get_owned(db, payload.upload_id, user.id)
    if asset is None or asset.extension != "apk":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reusable APK not found")

    service = _service(settings)
    temp_dir = service.root / "_repository_reuse" / str(asset.id)
    temp_path = temp_dir / asset.filename
    await UploadRepositoryService.materialize(db, asset.id, user.id, temp_path)
    reader = _AsyncPathReader(temp_path)
    try:
        job_id, _ = await service.save_upload_stream(
            asset.filename,
            reader,
            str(user.id),
            context=payload.context,
            max_bytes=settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024,
        )
    finally:
        await reader.close()
        await asyncio.to_thread(shutil.rmtree, temp_dir, True)

    await _link_repository_asset(db, service, job_id, asset.id)
    background_tasks.add_task(service.analyze_safely, job_id)
    result = await service.get_job_status(job_id)
    return await _mark_repository_available(db, result, user.id)


@router.get("/jobs/latest", response_model=AutopilotJobStatus | None)
async def get_latest_autopilot_job(
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    """Restore the latest result, including repository-backed APK availability."""
    service = _service(settings)
    record = await db.scalar(
        select(AutopilotJob)
        .where(AutopilotJob.owner_id == user.id)
        .order_by(AutopilotJob.created_at.desc())
        .limit(1)
    )
    if record is None:
        result = await service.get_latest_job_status(str(user.id))
        return result

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
    """Return progress and recover an interrupted repository-backed analysis."""
    service = _service(settings)
    job = await _require_owned_job(service, job_id, user)
    local_path = job.get("apk_path")
    record = await _job_record(db, job_id, user.id)
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
    """Compile generated test designs into QTX Test IR and Appium Python previews."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    try:
        analysis = await service.load_analysis(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Autopilot analysis is not complete")
    return AutopilotIRCompiler().compile_bundle(analysis)


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
    await _ensure_local_artifact(db, service, job_id, user)
    return await service.execute_smoke(job_id, payload)
