"""Encrypted, reusable values collected by an Autopilot checkpoint."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutopilotInputRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One encrypted checkpoint value or synthetic-data generator recipe.

    Values are scoped to the owner, project and stable Autopilot surface so a
    saved credential can be reused only for the same target.  The plaintext
    value is never stored; ``encrypted_value`` is Fernet ciphertext and is
    decrypted only inside the controlled runner when it needs it.
    """

    __tablename__ = "autopilot_input_records"
    __table_args__ = (
        Index(
            "ix_autopilot_input_records_scope_key",
            "owner_id",
            "project_id",
            "surface_key",
            "input_key",
            "updated_at",
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    surface_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    input_key: Mapped[str] = mapped_column(String(120), nullable=False)
    label: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="test_data")
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="provide")
    save_for_reuse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    encrypted_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generator_spec: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
