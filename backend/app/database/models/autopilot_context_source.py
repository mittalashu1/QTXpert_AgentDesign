"""Durable provenance rows for the Autopilot context pack."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, Float, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutopilotContextSource(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One source signal used (or intentionally not used) by a run.

    The source row stores only bounded metadata and opaque references.  Raw
    document content and credentials stay in their existing stores.
    """

    __tablename__ = "autopilot_context_sources"
    __table_args__ = (
        UniqueConstraint("autopilot_job_id", "source_id", name="uq_autopilot_context_sources_job_source"),
        Index("ix_autopilot_context_sources_owner_project", "owner_id", "project_id"),
    )

    autopilot_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("autopilot_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    source_id: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(180), nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    trust_level: Mapped[str] = mapped_column(String(12), nullable=False, default="medium")
    observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    influenced_plan_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    influenced_test_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    retrieved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

