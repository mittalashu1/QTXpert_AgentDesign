"""Data access for generation runs and their test cases."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models.generation_run import GenerationRun


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
