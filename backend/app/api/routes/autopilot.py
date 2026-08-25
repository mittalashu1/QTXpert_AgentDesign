"""Authenticated API endpoints for the Android-first Autopilot prototype."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps.auth_deps import get_current_user
from app.config import Settings, get_settings
from app.database.models.user import User
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAutomationBundle,
    AutopilotExecutionRequest,
    AutopilotExecutionResult,
    AutopilotJobStatus,
    AutopilotProviderStatus,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.autopilot_ir import AutopilotIRCompiler

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
    file: UploadFile = File(...),
    context: str = Form(default=""),
):
    """Upload and analyze an Android APK, then create an initial autonomous QA plan."""
    filename = file.filename or "application.apk"
    if not filename.lower().endswith(".apk"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The current prototype supports Android APK files. IPA support is the next platform milestone.",
        )

    max_bytes = settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"APK exceeds the {settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB}MB Autopilot prototype limit",
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if len(data) < 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="APK file is empty or invalid")

    service = _service(settings)
    job_id, _ = await service.save_upload(filename, data, str(user.id), context=context)
    background_tasks.add_task(service.analyze_safely, job_id)
    return await service.get_job_status(job_id)


@router.get("/jobs/{job_id}", response_model=AutopilotJobStatus)
async def get_autopilot_job_status(
    job_id: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
):
    """Return progress without holding a request open while an APK is analyzed."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    return await service.get_job_status(job_id)


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
):
    """Run the safe launch smoke against BrowserStack or a configured Appium endpoint."""
    service = _service(settings)
    await _require_owned_job(service, job_id, user)
    return await service.execute_smoke(job_id, payload)
