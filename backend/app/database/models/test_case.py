"""TestCase model - the structured generated artifact."""
import enum
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base
from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.database.models.generation_run import GenerationRun


class TestCaseType(str, enum.Enum):
    FUNCTIONAL = "functional"
    NEGATIVE = "negative"
    BOUNDARY = "boundary"
    INTEGRATION = "integration"
    API = "api"
    DATABASE = "database"
    SECURITY = "security"
    ACCESSIBILITY = "accessibility"
    USABILITY = "usability"
    PERFORMANCE = "performance"
    REGRESSION = "regression"
    EXPLORATORY = "exploratory"
    DATA_VALIDATION = "data_validation"
    WORKFLOW = "workflow"
    ROLE_BASED = "role_based"
    PERMISSION = "permission"
    MAKER_CHECKER = "maker_checker"
    ERROR_HANDLING = "error_handling"
    LOCALIZATION = "localization"
    BROWSER_COMPATIBILITY = "browser_compatibility"
    MOBILE = "mobile"
    CROSS_PLATFORM = "cross_platform"


class Priority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Severity(str, enum.Enum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    TRIVIAL = "trivial"


class RiskLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TestCase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "test_cases"

    generation_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("generation_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("requirements.id"), nullable=True
    )

    test_case_key: Mapped[str] = mapped_column(String(50), nullable=False)
    requirement_traceability: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    test_type: Mapped[TestCaseType] = mapped_column(
        Enum(TestCaseType, name="test_case_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]), 
        nullable=False
    )
    scenario: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[Priority] = mapped_column(Enum(Priority, name="priority"), nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False)

    preconditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    test_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    post_conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_automation_candidate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    automation_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risk_level", values_callable=lambda enum_cls: [e.value for e in enum_cls]), 
        default=RiskLevel.MEDIUM, nullable=False
    )

    generation_run: Mapped["GenerationRun"] = relationship(back_populates="test_cases")
