"""API schemas for the shared QTXpert Upload Repository."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UploadedAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: Optional[UUID] = None
    filename: str
    extension: str = ""
    content_type: Optional[str] = None
    category: str
    source_module: str
    storage_backend: str
    size_bytes: int
    sha256: str
    status: str
    created_at: datetime
    updated_at: datetime


class ReuseUploadedAssetRequest(BaseModel):
    upload_id: UUID
    context: str = Field(default="", max_length=8000)
