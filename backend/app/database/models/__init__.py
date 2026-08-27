"""Aggregates all ORM models so Alembic autogenerate can discover them."""
from app.database.models.user import User, UserRole  # noqa: F401
from app.database.models.project import Project  # noqa: F401
from app.database.models.requirement import (  # noqa: F401
    Requirement,
    RequirementSource,
    RequirementStatus,
)
from app.database.models.generation_run import GenerationRun, RunStatus  # noqa: F401
from app.database.models.test_case import (  # noqa: F401
    TestCase,
    TestCaseType,
    Priority,
    Severity,
    RiskLevel,
)
from app.database.models.config_and_audit import ApiConfiguration, AuditLog  # noqa: F401
from app.database.models.execution import (  # noqa: F401
    Defect, DefectStatus, ExecutionResult, ExecutionRun, ExecutionStatus, ResultStatus,
)
from app.database.models.llm_usage import LLMUsageEvent  # noqa: F401
from app.database.models.uploaded_asset import UploadedAsset, UploadedAssetChunk  # noqa: F401
from app.database.models.autopilot_job import AutopilotJob  # noqa: F401
from app.database.models.autopilot_execution import AutopilotExecution  # noqa: F401
from app.database.models.document_intelligence import (  # noqa: F401
    DocumentAnalysisRun,
    DocumentFinding,
)

__all__ = [
    "User", "UserRole", "Project", "Requirement", "RequirementSource", "RequirementStatus",
    "GenerationRun", "RunStatus", "TestCase", "TestCaseType", "Priority", "Severity", "RiskLevel",
    "ApiConfiguration", "AuditLog", "ExecutionRun", "ExecutionResult", "ExecutionStatus", "ResultStatus",
    "Defect", "DefectStatus", "LLMUsageEvent", "UploadedAsset", "UploadedAssetChunk", "AutopilotJob", "AutopilotExecution",
    "DocumentAnalysisRun", "DocumentFinding",
]
