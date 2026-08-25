"""Persisted provider usage records used by the admin cost dashboard."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.mixins import UUIDPrimaryKeyMixin
from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LLMUsageEvent(Base, UUIDPrimaryKeyMixin):
    """One completed LLM request and its best-effort cost estimate.

    Usage is intentionally independent of a project/user foreign key. The
    provider abstraction can be called from background work as well as HTTP
    requests, and the admin view reports workspace-wide consumption.
    """

    __tablename__ = "llm_usage_events"
    __table_args__ = (
        Index("ix_llm_usage_events_created_at", "created_at"),
        Index("ix_llm_usage_events_provider_model", "provider", "model"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(30), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 10), nullable=True
    )
