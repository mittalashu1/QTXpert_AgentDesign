"""Restart recovery for in-flight Autopilot APK analysis jobs.

Render replaces the process (and its local filesystem) during a deployment. APK
bytes are durable in the project Upload Repository, while the analysis worker is
not. On application startup this module finds recently in-flight jobs,
re-materializes their APK, and restarts analysis from the beginning. Re-running
analysis is intentionally idempotent: generated analysis replaces the same job's
result instead of creating duplicate jobs or test portfolios.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import Settings
from app.database.models.autopilot_job import AutopilotJob
from app.database.session import AsyncSessionLocal
from app.services.autopilot import AutopilotPrototypeService
from app.services.upload_repository import UploadRepositoryService

logger = logging.getLogger(__name__)


async def _resume_one(settings: Settings, job_id: str) -> None:
    """Materialize one APK from durable storage and restart its analysis."""
    service = AutopilotPrototypeService(settings)
    async with AsyncSessionLocal() as db:
        record = await db.scalar(select(AutopilotJob).where(AutopilotJob.job_id == job_id))
        if record is None or record.status not in {"uploaded", "analyzing"}:
            return

        if record.repository_asset_id is None:
            record.status = "failed"
            record.stage = "failed"
            record.progress = 100
            record.error = (
                "Analysis was interrupted by a service restart and this legacy APK is not "
                "available in the Upload Repository. Upload the APK once more."
            )
            await db.commit()
            return

        target = service.root / record.job_id / Path(record.filename or "application.apk").name
        record.stage = "recovering_after_restart"
        record.progress = max(10, min(int(record.progress or 0), 90))
        record.error = None
        await db.commit()

        try:
            await UploadRepositoryService.materialize(
                db,
                record.repository_asset_id,
                record.owner_id,
                target,
                settings=settings,
            )
        except Exception as exc:
            record = await db.scalar(select(AutopilotJob).where(AutopilotJob.job_id == job_id))
            if record is not None:
                record.status = "failed"
                record.stage = "failed"
                record.progress = 100
                record.error = f"Could not restore APK after service restart: {type(exc).__name__}: {exc}"[:1000]
                await db.commit()
            logger.exception("Autopilot APK recovery failed job_id=%s", job_id)
            return

    # update_job persists the new disposable path in both local metadata and DB.
    await service.update_job(
        job_id,
        apk_path=str(target),
        status="analyzing",
        stage="recovering_after_restart",
        error=None,
    )
    logger.info("Restarting interrupted Autopilot analysis job_id=%s", job_id)
    await service.analyze_safely(job_id)


async def recover_interrupted_autopilot_jobs(settings: Settings) -> int:
    """Recover recent in-flight jobs from the previous process, one at a time.

    A 24-hour window prevents very old abandoned jobs from unexpectedly consuming
    compute after a later deployment. The latest ten jobs are enough for the
    current single-worker prototype and keep startup recovery bounded.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        async with AsyncSessionLocal() as db:
            rows = await db.scalars(
                select(AutopilotJob)
                .where(
                    AutopilotJob.status.in_(["uploaded", "analyzing"]),
                    AutopilotJob.updated_at >= cutoff,
                )
                .order_by(AutopilotJob.updated_at.desc())
                .limit(10)
            )
            job_ids = [row.job_id for row in rows.all()]
    except Exception as exc:
        # A database quota outage must not make a healthy HTTP process look
        # like an application crash. The health endpoint reports the same
        # dependency state without flooding the production error log.
        logger.warning("Unable to inspect interrupted Autopilot jobs during startup: %s", exc)
        return 0

    # A single APK parse can allocate a large resource table. Starting several
    # recovery workers at once made the 512 MiB Render instance hit its memory
    # limit during deploys. The caller already runs this coroutine in a detached
    # startup task, so processing one job at a time does not delay HTTP startup.
    for job_id in job_ids:
        try:
            await _resume_one(settings, job_id)
        except Exception:
            logger.exception("Unexpected Autopilot restart recovery error job_id=%s", job_id)

    if job_ids:
        logger.warning(
            "Scheduled restart recovery for %d interrupted Autopilot job(s): %s",
            len(job_ids),
            ", ".join(job_id[:8] for job_id in job_ids),
        )
    return len(job_ids)

