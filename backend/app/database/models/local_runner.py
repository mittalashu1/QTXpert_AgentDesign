"""Per-project Windows/mobile runners and durable execution leases."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


class LocalDeviceRunner(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "local_device_runners"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending", index=True)
    capabilities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enrollment_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enrollment_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    runner_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LocalRunnerJob(Base, TimestampMixin):
    """ExecutionRun lease state, separate from product run/result data."""
    __tablename__ = "local_runner_jobs"

    execution_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("execution_runs.id", ondelete="CASCADE"), primary_key=True
    )
    runner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("local_device_runners.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", server_default="queued", index=True)
    lease_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
