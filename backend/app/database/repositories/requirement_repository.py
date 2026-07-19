"""Data access for projects and requirements."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.project import Project
from app.database.models.requirement import Requirement, RequirementSource


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(self, name: str, description: Optional[str], owner_id: UUID) -> Project:
        project = Project(name=name, description=description, owner_id=owner_id)
        self._db.add(project)
        await self._db.commit()
        await self._db.refresh(project)
        return project

    async def list_for_owner(self, owner_id: UUID) -> List[Project]:
        result = await self._db.execute(select(Project).where(Project.owner_id == owner_id))
        return list(result.scalars().all())

    async def get(self, project_id: UUID) -> Optional[Project]:
        result = await self._db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()


class RequirementRepository:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create(
        self,
        project_id: UUID,
        title: str,
        source: RequirementSource,
        raw_content: str,
        source_file_path: Optional[str] = None,
        external_key: Optional[str] = None,
    ) -> Requirement:
        requirement = Requirement(
            project_id=project_id,
            title=title,
            source=source,
            raw_content=raw_content,
            source_file_path=source_file_path,
            external_key=external_key,
        )
        self._db.add(requirement)
        await self._db.commit()
        await self._db.refresh(requirement)
        return requirement

    async def list_for_project(self, project_id: UUID) -> List[Requirement]:
        result = await self._db.execute(
            select(Requirement).where(Requirement.project_id == project_id)
        )
        return list(result.scalars().all())

    async def get_many(self, requirement_ids: List[UUID]) -> List[Requirement]:
        result = await self._db.execute(
            select(Requirement).where(Requirement.id.in_(requirement_ids))
        )
        return list(result.scalars().all())
