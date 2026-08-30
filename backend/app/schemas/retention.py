"""Request/response contracts for generated-data retention."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RetentionCleanupRequest(BaseModel):
    """Explicit confirmation and optional policy overrides for cleanup."""

    confirm: bool = Field(
        default=False,
        description="Must be true to delete any database rows or object-store files.",
    )
    days: int | None = Field(default=None, ge=1, le=3650)
    keep_latest: int | None = Field(default=None, ge=0, le=100)


class RetentionSummaryOut(BaseModel):
    cutoff: datetime
    keep_latest: int
    dry_run: bool
    candidates: dict[str, int]
    protected: dict[str, int]
    deleted: dict[str, int]
    candidate_total: int
    deleted_total: int
    deleted_bytes: int
    local_paths_removed: int
    storage_failures: list[str]
    local_path_failures: list[str]

    @classmethod
    def from_summary(cls, summary: Any) -> "RetentionSummaryOut":
        return cls(**summary.as_dict())
