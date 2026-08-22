"""Data access for generation runs and their test cases."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models.generation_run import GenerationRun, RunStatus
from app.database.models.project import Project


class GenerationRunRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def get(self, run_id: UUID) -> Optional[GenerationRun]:
        result = await self._db.execute(
            select(GenerationRun)
            .options(selectinload(GenerationRun.test_cases))
            .where(GenerationRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_for_project(self, project_id: UUID) -> List[GenerationRun]:
        result = await self._db.execute(
            select(GenerationRun)
            .options(selectinload(GenerationRun.test_cases))
            .where(GenerationRun.project_id == project_id)
            .order_by(GenerationRun.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_for_owner(self, run_id: UUID, owner_id: UUID) -> Optional[GenerationRun]:
        result = await self._db.execute(
            select(GenerationRun)
            .join(Project, GenerationRun.project_id == Project.id)
            .options(selectinload(GenerationRun.test_cases))
            .where(GenerationRun.id == run_id, Project.owner_id == owner_id)
        )
        return result.scalar_one_or_none()

    async def fail_stale_for_project(self, project_id: UUID, stale_after_seconds: int) -> None:
        """Expose abandoned web-process jobs as failed instead of polling forever.

        This is a recovery guard for the current in-process worker. A durable queue
        remains the next scalability step, but users can safely start a fresh run
        when a deploy or restart interrupts an existing one.
        """
        active_statuses = [
            RunStatus.PENDING,
            RunStatus.NORMALIZING,
            RunStatus.ANALYZING,
            RunStatus.GENERATING_SCENARIOS,
            RunStatus.GENERATING_TEST_CASES,
            RunStatus.RISK_ANALYSIS,
        ]
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
        result = await self._db.execute(
            update(GenerationRun)
            .where(
                GenerationRun.project_id == project_id,
                GenerationRun.status.in_(active_statuses),
                GenerationRun.updated_at < cutoff,
            )
            .values(
                status=RunStatus.FAILED,
                error_message=(
                    "Generation did not report progress in time and may have been interrupted. "
                    "Please start a new generation."
                ),
            )
        )
        if result.rowcount:
            await self._db.commit()

