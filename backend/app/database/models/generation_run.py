"""GenerationRun model - one execution of the AI test design workflow."""
import enum
import uuid
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Enum, Float, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.project import Project
    from app.database.models.test_case import TestCase


class RunStatus(str, enum.Enum):
    PENDING = "pending"
    NORMALIZING = "normalizing"
    ANALYZING = "analyzing"
    GENERATING_SCENARIOS = "generating_scenarios"
    GENERATING_TEST_CASES = "generating_test_cases"
    RISK_ANALYSIS = "risk_analysis"
    COMPLETED = "completed"
    FAILED = "failed"


class GenerationRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "generation_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]), 
        default=RunStatus.PENDING, nullable=False
    )
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)

    requirement_summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    business_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    functional_breakdown: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    test_scenarios: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    risk_analysis: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    processing_time_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="generation_runs")
    test_cases: Mapped[List["TestCase"]] = relationship(
        back_populates="generation_run", cascade="all, delete-orphan"
    )
