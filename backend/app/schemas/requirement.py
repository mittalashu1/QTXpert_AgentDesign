from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.database.models.requirement import RequirementSource, RequirementStatus


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: Optional[str]
    created_at: datetime


class DirectPromptRequest(BaseModel):
    project_id: UUID
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)


class ReuseRequirementRequest(BaseModel):
    """Create/reuse a requirement from an asset already in the repository."""

    project_id: UUID
    upload_id: UUID


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    source: RequirementSource
    status: RequirementStatus
    extracted_metadata: Optional[dict[str, Any]] = None
    created_at: datetime
