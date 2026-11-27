"""Outbound-only protocol for project-scoped local Android device runners.

The runner initiates every request over HTTPS. Appium is never exposed to the
internet; the API sends bounded execution manifests and the runner downloads
the selected repository APK through a lease-scoped endpoint.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps.auth_deps import get_current_user
from app.config import get_settings
from app.database.models.execution import ExecutionResult, ExecutionRun, ExecutionStatus, ResultStatus
from app.database.models.local_runner import LocalAutopilotSession, LocalDeviceRunner, LocalRunnerJob
from app.database.models.project import Project
from app.database.models.user import User
from app.database.models.uploaded_asset import UploadedAsset
from app.database.session import get_db_session
from app.services.defect_logging import secret_safe_text
from app.services.authored_execution import prepare_authored_cases, record_ui_outcome
from app.services.local_autopilot import APK_SERIAL, pack, unpack
from app.services.upload_repository import UploadRepositoryService

router = APIRouter(prefix="/local-runners", tags=["local-device-runners"])
logger = logging.getLogger(__name__)
LEASE_SECONDS = 90
MAX_ATTEMPTS = 3
SCREENSHOT_LIMIT = 5 * 1024 * 1024
PAGE_SOURCE_LIMIT = 2 * 1024 * 1024


class RunnerEnrollmentRequest(BaseModel):
    project_id: UUID
    name: str = Field(default="Windows Android runner", min_length=1, max_length=120)


class RunnerPairRequest(BaseModel):
    enrollment_token: str = Field(min_length=20, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    os_name: str = Field(default="Windows", min_length=1, max_length=40)
    platforms: list[str] = Field(default_factory=lambda: ["android"], min_length=1, max_length=3)
    device_names: list[str] = Field(default_factory=list, max_length=20)


class RunnerCaseResult(BaseModel):
    result_id: UUID
    status: str = Field(pattern="^(passed|failed|blocked|skipped)$")
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)
    error_message: str | None = Field(default=None, max_length=4000)
    business_reference: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_.:-]{4,128}$")


class RunnerCompleteRequest(BaseModel):
    results: list[RunnerCaseResult] = Field(min_length=1, max_length=2000)
    current_package: str | None = Field(default=None, max_length=300)
    current_activity: str | None = Field(default=None, max_length=500)
    device_name: str | None = Field(default=None, max_length=120)
    platform_version: str | None = Field(default=None, max_length=40)
    screenshot_base64: str | None = Field(default=None, max_length=7_100_000)
    page_source_base64: str | None = Field(default=None, max_length=2_900_000)


class RunnerFailRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _derived_lease_token(runner_secret: str, run_id: UUID, attempt: int) -> str:
    # Deterministic only for this runner/run/attempt, so a lost claim response
    # can be replayed without storing a plaintext lease secret in the database.
    message = f"qtxpert-local-runner-lease:{run_id}:{attempt}".encode("utf-8")
    return hmac.new(runner_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


async def _owned_project(db: AsyncSession, project_id: UUID, owner_id: UUID) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == owner_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _authenticate_runner(
    db: AsyncSession,
    runner_id: UUID,
    authorization: str | None,
    *,
    lock: bool = False,
) -> tuple[LocalDeviceRunner, str]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Runner authentication required")
    token = authorization[7:].strip()
    if len(token) < 32:
        raise HTTPException(status_code=401, detail="Runner authentication failed")
    query = (
        select(LocalDeviceRunner)
        .join(User, User.id == LocalDeviceRunner.owner_id)
        .join(Project, Project.id == LocalDeviceRunner.project_id)
        .where(
            LocalDeviceRunner.id == runner_id,
            LocalDeviceRunner.status == "active",
            User.is_active.is_(True),
            Project.owner_id == LocalDeviceRunner.owner_id,
        )
    )
    runner = await db.scalar(query.with_for_update(of=LocalDeviceRunner) if lock else query)
    if runner is None or not runner.runner_token_hash or not hmac.compare_digest(
        runner.runner_token_hash, _digest(token)
    ):
        raise HTTPException(status_code=401, detail="Runner authentication failed")
    return runner, token


async def _leased_job(
    db: AsyncSession,
    *,
    runner_id: UUID,
    run_id: UUID,
    lease_token: str | None,
    lock: bool = False,
) -> LocalRunnerJob:
    if not lease_token or len(lease_token) > 128:
        raise HTTPException(status_code=401, detail="Execution lease is missing or invalid")
    statement = select(LocalRunnerJob).where(
        LocalRunnerJob.execution_run_id == run_id,
        LocalRunnerJob.runner_id == runner_id,
        LocalRunnerJob.status == "leased",
    )
    if lock:
        statement = statement.with_for_update()
    job = await db.scalar(statement)
    if job is None or not job.lease_token_hash or not hmac.compare_digest(
        job.lease_token_hash, _digest(lease_token)
    ):
        raise HTTPException(status_code=409, detail="Execution lease is no longer active")
    if job.lease_expires_at and job.lease_expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Execution lease expired; the job can be retried")
    return job


@router.post("/enrollment", status_code=status.HTTP_201_CREATED)
async def create_enrollment(
    payload: RunnerEnrollmentRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    await _owned_project(db, payload.project_id, user.id)
    token = f"qtxenroll_{secrets.token_urlsafe(32)}"
    runner = LocalDeviceRunner(
        owner_id=user.id,
        project_id=payload.project_id,
        name=payload.name.strip(),
        status="pending",
        capabilities={"platforms": ["android"]},
        enrollment_token_hash=_digest(token),
        enrollment_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(runner)
    await db.commit()
    return {
        "runner_id": str(runner.id),
        "project_id": str(runner.project_id),
        "enrollment_token": token,
        "expires_in_seconds": 600,
        "message": "Use this one-time token to pair the Windows runner. It is shown only once.",
    }


@router.post("/pair", status_code=status.HTTP_201_CREATED)
async def pair_runner(
    payload: RunnerPairRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
):
    normalized_platforms = sorted({item.strip().lower() for item in payload.platforms})
    if not normalized_platforms or any(item not in {"android", "ios"} for item in normalized_platforms):
        raise HTTPException(status_code=422, detail="Runner platforms must be Android and/or iOS.")
    if normalized_platforms != ["android"]:
        raise HTTPException(status_code=422, detail="This Windows runner currently supports Android only. iOS requires a separate macOS runner build.")
    runner = await db.scalar(
        select(LocalDeviceRunner)
        .where(
            LocalDeviceRunner.enrollment_token_hash == _digest(payload.enrollment_token),
            LocalDeviceRunner.status == "pending",
        )
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if runner is None or runner.enrollment_expires_at is None or runner.enrollment_expires_at <= now:
        raise HTTPException(status_code=401, detail="Enrollment token is invalid or expired")
    runner_token = f"qtxrunner_{secrets.token_urlsafe(48)}"
    runner.status = "active"
    runner.name = payload.name.strip()
    runner.capabilities = {
        "os": payload.os_name.strip()[:40],
        "platforms": normalized_platforms,
        "devices": [name.strip()[:120] for name in payload.device_names if name.strip()][:20],
    }
    runner.enrollment_token_hash = None
    runner.enrollment_expires_at = None
    runner.runner_token_hash = _digest(runner_token)
    runner.last_seen_at = now
    await db.commit()
    return {
        "runner_id": str(runner.id),
        "project_id": str(runner.project_id),
        "runner_token": runner_token,
        "status": "active",
        "message": "Pairing succeeded. Store the token in Windows DPAPI-protected local storage; it cannot be recovered from QTXpert.",
    }


@router.get("")
async def list_runners(
    project_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    await _owned_project(db, project_id, user.id)
    rows = await db.scalars(
        select(LocalDeviceRunner)
        .where(LocalDeviceRunner.project_id == project_id, LocalDeviceRunner.owner_id == user.id)
        .order_by(LocalDeviceRunner.created_at.desc())
    )
    now = datetime.now(timezone.utc)
    return [
        {
            "id": str(row.id),
            "name": row.name,
            "status": "online" if row.status == "active" and row.last_seen_at and row.last_seen_at > now - timedelta(seconds=75) else row.status,
            "platforms": row.capabilities.get("platforms", []),
            "devices": row.capabilities.get("devices", []),
            "autopilot_android": bool(row.capabilities.get("autopilot_android")),
            "last_seen_at": row.last_seen_at,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.delete("/{runner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_runner(
    runner_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    runner = await db.scalar(
        select(LocalDeviceRunner).where(LocalDeviceRunner.id == runner_id, LocalDeviceRunner.owner_id == user.id).with_for_update()
    )
    if runner is None:
        raise HTTPException(status_code=404, detail="Runner not found")
    runner.status = "revoked"
    runner.runner_token_hash = None
    runner.enrollment_token_hash = None
    reservation = await db.get(LocalAutopilotSession, runner.id, with_for_update=True)
    if reservation is not None:
        await db.delete(reservation)
    jobs = await db.scalars(
        select(LocalRunnerJob).where(LocalRunnerJob.runner_id == runner.id, LocalRunnerJob.status == "leased")
    )
    for job in jobs:
        run = await db.get(ExecutionRun, job.execution_run_id)
        job.status = "queued"
        job.runner_id = None
        job.lease_token_hash = None
        job.lease_expires_at = None
        if run and run.status == ExecutionStatus.RUNNING:
            run.status = ExecutionStatus.QUEUED
            run.started_at = None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{runner_id}/heartbeat")
async def runner_heartbeat(
    runner_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
):
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    runner.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "online", "server_time": runner.last_seen_at.isoformat()}


@router.post("/{runner_id}/jobs/claim")
async def claim_job(
    runner_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
):
    runner, runner_secret = await _authenticate_runner(db, runner_id, authorization, lock=True)
    now = datetime.now(timezone.utc)
    runner.last_seen_at = now
    reservation = await db.get(LocalAutopilotSession, runner.id)
    if reservation is not None and reservation.expires_at > now:
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    platforms = (runner.capabilities or {}).get("platforms", [])
    allowed = [ExecutionRun.target_kind == item for item in platforms if item in {"android", "ios"}]
    if not allowed:
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    active_same_runner = and_(
        LocalRunnerJob.status == "leased",
        LocalRunnerJob.runner_id == runner.id,
        LocalRunnerJob.lease_expires_at > now,
    )
    claimable = or_(
        LocalRunnerJob.status == "queued",
        and_(LocalRunnerJob.status == "leased", LocalRunnerJob.lease_expires_at <= now),
        active_same_runner,
    )
    statement = (
        select(LocalRunnerJob)
        .join(ExecutionRun, ExecutionRun.id == LocalRunnerJob.execution_run_id)
        .where(
            ExecutionRun.project_id == runner.project_id,
            ExecutionRun.provider == "local_runner",
            or_(
                ExecutionRun.target_metadata["selected_runner_id"].as_string().is_(None),
                ExecutionRun.target_metadata["selected_runner_id"].as_string() == str(runner.id),
            ),
            ExecutionRun.status.in_([ExecutionStatus.QUEUED, ExecutionStatus.RUNNING]),
            or_(*allowed),
            claimable,
        )
        .order_by(ExecutionRun.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = await db.scalar(statement)
    if job is None:
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    run = await db.scalar(
        select(ExecutionRun)
        .options(
            selectinload(ExecutionRun.results).selectinload(ExecutionResult.test_case),
            selectinload(ExecutionRun.results).selectinload(ExecutionResult.execution_plan_case),
            selectinload(ExecutionRun.execution_plan),
        )
        .where(ExecutionRun.id == job.execution_run_id)
    )
    if run is None:
        job.status = "failed"
        job.last_error = "Execution run no longer exists"
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    pending_results = [item for item in run.results if item.status == ResultStatus.PENDING]
    authored_pending = [item for item in pending_results if (item.execution_spec or {}).get("automation")]
    if authored_pending and not (runner.capabilities or {}).get("autopilot_android"):
        await db.commit()
        return Response(status_code=204)
    dispatched_business = [item for item in authored_pending if (item.evidence or {}).get("business_dispatch")]
    if dispatched_business and job.status == "leased" and job.lease_expires_at and job.lease_expires_at > now:
        await db.commit()
        return Response(status_code=204)
    for item in dispatched_business:
        item.status = ResultStatus.BLOCKED
        item.error_message = "The device stopped after the transaction was dispatched. Check the UAT ledger before retrying."
        item.evidence = {**item.evidence, "business_verification": "dispatch_uncertain"}
    pending_results = [item for item in pending_results if item.status == ResultStatus.PENDING]
    prepared = await prepare_authored_cases(db, get_settings(), run, pending_results) if authored_pending else {}
    pending_results = [item for item in pending_results if item.status == ResultStatus.PENDING]
    if not pending_results:
        # A plan can contain only cases blocked by preflight. Finalize that
        # run without starting an empty device session or asking the runner to
        # submit an empty result set.
        job.status = "completed"
        job.lease_token_hash = None
        job.lease_expires_at = None
        run.passed_tests = sum(item.status == ResultStatus.PASSED for item in run.results)
        run.failed_tests = sum(item.status == ResultStatus.FAILED for item in run.results)
        run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
        run.status = ExecutionStatus.COMPLETED
        run.completed_at = now
        if run.execution_plan is not None:
            run.execution_plan.status = "completed"
        await db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if job.status == "leased" and job.runner_id == runner.id and job.lease_expires_at and job.lease_expires_at > now:
        attempt = job.attempt_count
    else:
        if job.attempt_count >= MAX_ATTEMPTS:
            job.status = "failed"
            job.last_error = "Runner lease expired after the retry limit"
            run.status = ExecutionStatus.FAILED
            run.completed_at = now
            for result in run.results:
                if result.status == ResultStatus.PENDING:
                    result.status = ResultStatus.BLOCKED
                    result.error_message = "Local runner stopped responding before completing this test."
            run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
            run.failed_tests = sum(item.status == ResultStatus.FAILED for item in run.results)
            await db.commit()
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        job.attempt_count += 1
        job.runner_id = runner.id
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        job.status = "leased"
        attempt = job.attempt_count
    lease_token = _derived_lease_token(runner_secret, run.id, attempt)
    job.lease_token_hash = _digest(lease_token)
    run.status = ExecutionStatus.RUNNING
    if run.started_at is None:
        run.started_at = now
    if run.execution_plan is not None:
        run.execution_plan.status = "running"

    asset = await UploadRepositoryService.get_owned(db, run.app_asset_id, runner.owner_id) if run.app_asset_id else None
    if asset is None or asset.project_id != run.project_id:
        raise HTTPException(status_code=409, detail="The selected application package is unavailable in this project repository")
    cases = []
    for result in pending_results:
        case = result.execution_plan_case or result.test_case
        spec = result.execution_spec or {}
        authored = prepared.get(result.id, {})
        if authored.get("business_case"):
            result.evidence = {"business_dispatch": now.isoformat()}
        cases.append({
            "result_id": str(result.id),
            "case_key": getattr(case, "test_case_key", ""),
            "title": getattr(case, "scenario", "Mobile test"),
            "steps": list(spec["legacy_steps"] if "legacy_steps" in spec else getattr(case, "steps", []) or []),
            "ledger_identity": spec.get("ledger_identity"),
            **authored,
        })
    await db.commit()
    return {
        "run_id": str(run.id),
        "lease_token": lease_token,
        "lease_seconds": LEASE_SECONDS,
        "target_kind": run.target_kind,
        "device_name": run.device_name,
        "platform_version": run.platform_version,
        "no_reset": bool((run.target_metadata or {}).get("no_reset", False)),
        "auto_grant_permissions": bool((run.target_metadata or {}).get("auto_grant_permissions", True)),
        "app_asset_id": str(asset.id),
        "app_filename": asset.filename,
        "app_sha256": asset.sha256,
        "app_size_bytes": asset.size_bytes,
        "artifact_path": f"{get_settings().API_V1_PREFIX}/local-runners/{runner.id}/jobs/{run.id}/artifact",
        "cases": cases,
    }


@router.post("/{runner_id}/jobs/{run_id}/heartbeat")
async def renew_job_lease(
    runner_id: UUID,
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_qtxpert_lease: Annotated[str | None, Header()] = None,
):
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    job = await _leased_job(db, runner_id=runner.id, run_id=run_id, lease_token=x_qtxpert_lease, lock=True)
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
    runner.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "leased", "lease_seconds": LEASE_SECONDS}


@router.get("/{runner_id}/jobs/{run_id}/artifact")
async def download_job_artifact(
    runner_id: UUID,
    run_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_qtxpert_lease: Annotated[str | None, Header()] = None,
):
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    await _leased_job(db, runner_id=runner.id, run_id=run_id, lease_token=x_qtxpert_lease)
    run = await db.get(ExecutionRun, run_id)
    if run is None or run.app_asset_id is None:
        raise HTTPException(status_code=404, detail="Application artifact not found")
    path = Path(tempfile.mkdtemp(prefix="qtxpert-runner-download-")) / ("application.ipa" if run.target_kind == "ios" else "application.apk")
    try:
        asset = await UploadRepositoryService.materialize(
            db, run.app_asset_id, runner.owner_id, path, settings=get_settings()
        )
    except FileNotFoundError as exc:
        path.parent.rmdir()
        raise HTTPException(status_code=404, detail="Application artifact is no longer in this project repository") from exc
    return FileResponse(
        path,
        filename=Path(asset.filename).name,
        media_type="application/octet-stream",
        background=BackgroundTask(_remove_download, path),
    )


def _remove_download(path: Path) -> None:
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


class AutopilotClaimRequest(BaseModel):
    worker_id: UUID
    devices: list[str] = Field(default_factory=list, max_length=20)


class AutopilotCommandAnswer(BaseModel):
    command_id: UUID
    response_json: str = Field(max_length=8_000_000)


@router.post("/{runner_id}/autopilot/claim")
async def claim_autopilot_session(
    runner_id: UUID,
    payload: AutopilotClaimRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
):
    if any(not APK_SERIAL.fullmatch(serial) for serial in payload.devices):
        raise HTTPException(status_code=400, detail="Invalid ADB device serial")
    runner, _ = await _authenticate_runner(db, runner_id, authorization, lock=True)
    now = datetime.now(timezone.utc)
    runner.last_seen_at = now
    runner.capabilities = {**runner.capabilities, "autopilot_android": True, "devices": payload.devices}
    reservation = await db.get(LocalAutopilotSession, runner.id, with_for_update=True)
    if reservation is not None and reservation.expires_at <= now:
        await db.delete(reservation)
        reservation = None
    if reservation is None or reservation.worker_id not in (None, payload.worker_id):
        await db.commit()
        return Response(status_code=204)
    asset = await db.scalar(select(UploadedAsset).where(
        UploadedAsset.id == reservation.asset_id,
        UploadedAsset.owner_id == runner.owner_id,
        UploadedAsset.project_id == runner.project_id,
        UploadedAsset.extension == "apk",
        UploadedAsset.status == "ready",
    ))
    if asset is None:
        await db.delete(reservation)
        await db.commit()
        return Response(status_code=204)
    reservation.worker_id = payload.worker_id
    manifest = {
        "session_id": str(reservation.session_id),
        "device_name": reservation.device_name,
        "package_name": reservation.package_name,
        "app_sha256": asset.sha256,
    }
    await db.commit()
    return manifest


async def _claimed_autopilot_session(
    db: AsyncSession, runner_id: UUID, session_id: UUID, authorization: str | None, worker_id: UUID,
) -> tuple[LocalDeviceRunner, LocalAutopilotSession]:
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    reservation = await db.get(LocalAutopilotSession, runner.id, with_for_update=True)
    if (
        reservation is None or reservation.session_id != session_id
        or reservation.worker_id != worker_id or reservation.expires_at <= datetime.now(timezone.utc)
    ):
        raise HTTPException(status_code=409, detail="The Autopilot device session has ended.")
    return runner, reservation


@router.post("/{runner_id}/autopilot/{session_id}/next")
async def next_autopilot_command(
    runner_id: UUID,
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_worker: Annotated[UUID, Header()],
    authorization: Annotated[str | None, Header()] = None,
):
    runner, reservation = await _claimed_autopilot_session(db, runner_id, session_id, authorization, x_qtxpert_worker)
    now = datetime.now(timezone.utc)
    heartbeat_due = runner.last_seen_at is None or runner.last_seen_at <= now - timedelta(seconds=20)
    if heartbeat_due:
        runner.last_seen_at = now
    if reservation.command_id is None or reservation.command_delivered or not reservation.command_payload:
        if heartbeat_due:
            await db.commit()
        return Response(status_code=204)
    body = {
        "command_id": str(reservation.command_id),
        **unpack(get_settings(), reservation.command_payload),
    }
    # Never replay an ambiguous device command after losing the response.
    reservation.command_delivered = True
    reservation.command_payload = None
    await db.commit()
    return body


@router.post("/{runner_id}/autopilot/{session_id}/answer", status_code=204)
async def answer_autopilot_command(
    runner_id: UUID,
    session_id: UUID,
    payload: AutopilotCommandAnswer,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_worker: Annotated[UUID, Header()],
    authorization: Annotated[str | None, Header()] = None,
):
    runner, reservation = await _claimed_autopilot_session(db, runner_id, session_id, authorization, x_qtxpert_worker)
    if reservation.command_id != payload.command_id or not reservation.command_delivered:
        raise HTTPException(status_code=409, detail="The Android command expired.")
    if reservation.command_answer is None:
        try:
            response = json.loads(payload.response_json)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Android command response.") from exc
        if not isinstance(response, dict):
            raise HTTPException(status_code=400, detail="Expected an Android command response object.")
        reservation.command_answer = pack(get_settings(), response)
        runner.last_seen_at = datetime.now(timezone.utc)
        await db.commit()
    return Response(status_code=204)


@router.get("/{runner_id}/autopilot/{session_id}/artifact")
async def download_autopilot_artifact(
    runner_id: UUID,
    session_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    x_qtxpert_worker: Annotated[UUID, Header()],
    authorization: Annotated[str | None, Header()] = None,
):
    runner, reservation = await _claimed_autopilot_session(db, runner_id, session_id, authorization, x_qtxpert_worker)
    owner_id, project_id = runner.owner_id, runner.project_id
    asset = await db.scalar(select(UploadedAsset.id).where(
        UploadedAsset.id == reservation.asset_id, UploadedAsset.project_id == project_id,
        UploadedAsset.owner_id == owner_id, UploadedAsset.extension == "apk", UploadedAsset.status == "ready",
    ))
    if asset is None:
        raise HTTPException(status_code=404, detail="The project APK is no longer available.")
    await db.rollback()
    path = Path(tempfile.mkdtemp(prefix="qtxpert-autopilot-download-")) / "application.apk"
    try:
        await UploadRepositoryService.materialize(db, asset, owner_id, path, settings=get_settings())
    except FileNotFoundError as exc:
        _remove_download(path)
        raise HTTPException(status_code=404, detail="The project APK is no longer available.") from exc
    except BaseException:
        _remove_download(path)
        raise
    return FileResponse(path, media_type="application/vnd.android.package-archive", background=BackgroundTask(_remove_download, path))


def _decode_evidence(value: str | None, limit: int, label: str) -> bytes | None:
    if not value:
        return None
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=f"{label} evidence is not valid base64") from exc
    if len(data) > limit:
        raise HTTPException(status_code=413, detail=f"{label} evidence exceeds the {limit // (1024 * 1024)}MB limit")
    return data


@router.post("/{runner_id}/jobs/{run_id}/complete")
async def complete_job(
    runner_id: UUID,
    run_id: UUID,
    payload: RunnerCompleteRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_qtxpert_lease: Annotated[str | None, Header()] = None,
):
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    job = await _leased_job(db, runner_id=runner.id, run_id=run_id, lease_token=x_qtxpert_lease, lock=True)
    run = await db.scalar(
        select(ExecutionRun)
        .options(selectinload(ExecutionRun.results), selectinload(ExecutionRun.execution_plan))
        .where(ExecutionRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Execution run not found")
    pending = {item.id: item for item in run.results if item.status == ResultStatus.PENDING}
    updates = {item.result_id: item for item in payload.results}
    if len(updates) != len(payload.results) or set(updates) != set(pending):
        raise HTTPException(status_code=409, detail="Runner results must contain each pending test exactly once")

    if payload.device_name:
        run.device_name = payload.device_name
    if payload.platform_version:
        run.platform_version = payload.platform_version

    screenshot = _decode_evidence(payload.screenshot_base64, SCREENSHOT_LIMIT, "Screenshot")
    page_source = _decode_evidence(payload.page_source_base64, PAGE_SOURCE_LIMIT, "Page source")
    evidence_ids: dict[str, str] = {}
    for key, content, filename, content_type in (
        ("screenshot_asset_id", screenshot, f"execution-{run.id}-local-runner.png", "image/png"),
        ("page_source_asset_id", page_source, f"execution-{run.id}-local-runner.xml", "application/xml"),
    ):
        if content is None:
            continue
        asset = await UploadRepositoryService.create_from_bytes(
            db,
            content,
            runner.owner_id,
            filename=filename,
            content_type=content_type,
            project_id=run.project_id,
            source_module="execution_report",
            category="execution_evidence",
            max_bytes=SCREENSHOT_LIMIT if key == "screenshot_asset_id" else PAGE_SOURCE_LIMIT,
            settings=get_settings(),
        )
        evidence_ids[key] = str(asset.id)

    for result_id, update in updates.items():
        result = pending[result_id]
        result.status = ResultStatus(update.status)
        result.duration_ms = update.duration_ms
        result.error_message = secret_safe_text(update.error_message or "")[:4000] or None
        result.evidence = {
            **(result.evidence or {}),
            "provider": "local_runner",
            "device_name": run.device_name,
            "platform_version": run.platform_version,
            "current_package": payload.current_package,
            "current_activity": payload.current_activity,
            **evidence_ids,
        }
        record_ui_outcome(result, update.business_reference)
    run.passed_tests = sum(item.status == ResultStatus.PASSED for item in run.results)
    run.failed_tests = sum(item.status == ResultStatus.FAILED for item in run.results)
    run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
    run.status = ExecutionStatus.COMPLETED
    run.completed_at = datetime.now(timezone.utc)
    run.target_metadata = {**(run.target_metadata or {}), **evidence_ids, "runner_id": str(runner.id)}
    if run.execution_plan is not None:
        run.execution_plan.status = "completed"
    job.status = "completed"
    job.lease_token_hash = None
    job.lease_expires_at = None
    runner.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(
        "Local runner completed execution run_id=%s passed=%s failed=%s blocked=%s",
        run.id, run.passed_tests, run.failed_tests, run.blocked_tests,
    )
    return {"run_id": str(run.id), "status": run.status.value, "passed": run.passed_tests, "failed": run.failed_tests, "blocked": run.blocked_tests, "evidence": evidence_ids}


@router.post("/{runner_id}/jobs/{run_id}/fail")
async def fail_job(
    runner_id: UUID,
    run_id: UUID,
    payload: RunnerFailRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_qtxpert_lease: Annotated[str | None, Header()] = None,
):
    runner, _ = await _authenticate_runner(db, runner_id, authorization)
    job = await _leased_job(db, runner_id=runner.id, run_id=run_id, lease_token=x_qtxpert_lease, lock=True)
    run = await db.scalar(
        select(ExecutionRun).options(selectinload(ExecutionRun.results), selectinload(ExecutionRun.execution_plan)).where(ExecutionRun.id == run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Execution run not found")
    safe_message = secret_safe_text(payload.message)[:2000]
    for result in run.results:
        if result.status == ResultStatus.PENDING:
            result.status = ResultStatus.BLOCKED
            result.error_message = safe_message or "The local runner could not complete this execution."
            result.evidence = {"provider": "local_runner", "device_name": run.device_name}
    run.blocked_tests = sum(item.status == ResultStatus.BLOCKED for item in run.results)
    run.failed_tests = sum(item.status == ResultStatus.FAILED for item in run.results)
    run.status = ExecutionStatus.FAILED
    run.completed_at = datetime.now(timezone.utc)
    if run.execution_plan is not None:
        run.execution_plan.status = "failed"
    job.status = "failed"
    job.last_error = safe_message
    job.lease_token_hash = None
    job.lease_expires_at = None
    await db.commit()
    logger.warning("Local runner failed execution run_id=%s message=%s", run.id, safe_message)
    return {"run_id": str(run.id), "status": run.status.value, "blocked": run.blocked_tests}
