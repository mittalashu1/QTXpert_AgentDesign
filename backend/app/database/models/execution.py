import enum
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

class ExecutionStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ResultStatus(str, enum.Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"

class DefectStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"

class ExecutionRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "execution_runs"
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ExecutionStatus] = mapped_column(Enum(ExecutionStatus, name="execution_status", values_callable=lambda e: [x.value for x in e]), default=ExecutionStatus.QUEUED, nullable=False)
    browser: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    total_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_tests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    results: Mapped[list["ExecutionResult"]] = relationship(back_populates="run", cascade="all, delete-orphan", lazy="selectin")

class ExecutionResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "execution_results"
    execution_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    test_case_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("test_cases.id"), nullable=False)
    status: Mapped[ResultStatus] = mapped_column(Enum(ResultStatus, name="execution_result_status", values_callable=lambda e: [x.value for x in e]), default=ResultStatus.PENDING, nullable=False)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    run: Mapped["ExecutionRun"] = relationship(back_populates="results")
    test_case = relationship("TestCase", lazy="joined")
    defects: Mapped[list["Defect"]] = relationship(back_populates="result", cascade="all, delete-orphan", lazy="selectin")

    @property
    def test_case_key(self) -> str:
        return self.test_case.test_case_key

    @property
    def scenario(self) -> str:
        return self.test_case.scenario

class Defect(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "defects"
    execution_result_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("execution_results.id", ondelete="CASCADE"), nullable=False, index=True)
    defect_key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[DefectStatus] = mapped_column(Enum(DefectStatus, name="defect_status", values_callable=lambda e: [x.value for x in e]), default=DefectStatus.OPEN, nullable=False)
    logged_by_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    result: Mapped["ExecutionResult"] = relationship(back_populates="defects")

