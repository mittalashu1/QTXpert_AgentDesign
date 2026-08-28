"""Versioned execution plans imported from generated Test Design suites."""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base

if TYPE_CHECKING:
    from app.database.models.execution import ExecutionResult, ExecutionRun
    from app.database.models.generation_run import GenerationRun
    from app.database.models.project import Project
    from app.database.models.test_case import TestCase
    from app.database.models.user import User


class ExecutionPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A user-controlled, reproducible selection from one Design run."""

    __tablename__ = "execution_plans"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Keep the imported snapshot if a historical Design run is ever removed.
    source_generation_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    suite_type: Mapped[str] = mapped_column(String(30), nullable=False, default="regression")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    source_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    cases: Mapped[List["ExecutionPlanCase"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="ExecutionPlanCase.selection_order",
        lazy="selectin",
    )
    execution_runs: Mapped[List["ExecutionRun"]] = relationship(
        back_populates="execution_plan", lazy="selectin"
    )

    @property
    def total_cases(self) -> int:
        return len(self.cases)

    @property
    def selected_cases(self) -> int:
        return sum(case.selected for case in self.cases)

    @property
    def selected_automated_cases(self) -> int:
        return sum(case.selected and case.execution_mode == "automated" for case in self.cases)

    @property
    def ready_cases(self) -> int:
        return sum(case.selected and case.execution_mode == "automated" and case.readiness == "ready" for case in self.cases)

    @property
    def blocked_cases(self) -> int:
        return sum(
            case.selected
            and case.execution_mode == "automated"
            and case.readiness in {"blocked", "approval_required"}
            for case in self.cases
        )


class ExecutionPlanCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A frozen Test Case snapshot belonging to an ExecutionPlan."""

    __tablename__ = "execution_plan_cases"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_test_case_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    selection_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    readiness: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    blocker_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Immutable fields copied from Test Design at import time.
    test_case_key: Mapped[str] = mapped_column(String(50), nullable=False)
    requirement_traceability: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    test_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scenario: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    preconditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    post_conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_automation_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    automation_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False, default="medium")

    plan: Mapped["ExecutionPlan"] = relationship(back_populates="cases")
    source_test_case: Mapped[Optional["TestCase"]] = relationship(lazy="joined")
    execution_results: Mapped[List["ExecutionResult"]] = relationship(
        back_populates="execution_plan_case", lazy="selectin"
    )

