"""API schemas for the shared QTXpert Upload Repository."""
from datetime import datetime
from typing import Literal, Optional
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
    profile_id: str = Field(default="uae_fintech", max_length=80)
    surface_action: Literal["ask", "new", "override"] = "ask"
    # Optional project documentation to reuse as analysis context. ``None``
    # means preserve the attachments from the previous run when rerunning;
    # an empty list deliberately clears them.
    document_asset_ids: Optional[list[UUID]] = Field(default=None, max_length=20)
    document_analysis_run_id: Optional[UUID] = Field(
        default=None,
        description="Optional completed Document Intelligence baseline linked to this analysis.",
    )

