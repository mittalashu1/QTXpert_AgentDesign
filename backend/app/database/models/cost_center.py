"""Durable Cost Center catalog refresh state.

The catalog itself is versioned in application code so links and documented
limits can be reviewed in source control.  This table stores only the
non-sensitive results of optional provider probes (for example, BrowserStack
parallel capacity or Cloudflare R2 object counts), together with refresh
metadata.  Provider credentials are never stored here.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CostCenterSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Last workspace-wide provider catalog refresh."""

    __tablename__ = "cost_center_snapshots"
    __table_args__ = (Index("ix_cost_center_snapshots_scope", "scope", unique=True),)

    # A single workspace snapshot is sufficient today.  Keeping this as a
    # scope column leaves room for per-organisation snapshots later without
    # changing the API contract.
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="unavailable")
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    refreshed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, default=_utcnow
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
