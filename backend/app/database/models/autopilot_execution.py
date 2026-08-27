"""Durable safe-smoke execution history for mobile Autopilot jobs."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutopilotExecution(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One immutable record of a safe smoke attempt.

    APK bytes and captured evidence are owned by the Upload Repository. This
    table keeps the execution request/result metadata and references those
    durable evidence assets so a page refresh or Render restart does not erase
    the run history.
    """

    __tablename__ = "autopilot_executions"
    __table_args__ = (
        Index("ix_autopilot_executions_job_created", "autopilot_job_id", "created_at"),
        Index("ix_autopilot_executions_owner_created", "owner_id", "created_at"),
    )

    autopilot_job_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("autopilot_jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    repository_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    appium_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    appium_app: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    no_reset: Mapped[bool] = mapped_column(default=False, nullable=False)
    auto_grant_permissions: Mapped[bool] = mapped_column(default=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    current_package: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    current_activity: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    screenshot_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    page_source_asset_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
