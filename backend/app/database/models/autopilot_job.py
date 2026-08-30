"""Durable metadata and analysis results for Autopilot runtime jobs."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutopilotJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One website or mobile target and its durable Autopilot state.

    Mobile binaries belong to the shared Upload Repository. ``apk_path`` is
    retained as a backwards-compatible name for the disposable local
    materialization used by the mobile workers; website jobs use ``target_url``.
    """

    __tablename__ = "autopilot_jobs"
    __table_args__ = (
        Index("ix_autopilot_jobs_owner_created", "owner_id", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    repository_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="android", server_default="android")
    target_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    apk_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    stage: Mapped[str] = mapped_column(String(80), nullable=False, default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    discovery: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    suite_execution: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    setup_profile: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
