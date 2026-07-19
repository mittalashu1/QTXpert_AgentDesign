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

__all__ = [
    "User",
    "UserRole",
    "Project",
    "Requirement",
    "RequirementSource",
    "RequirementStatus",
    "GenerationRun",
    "RunStatus",
    "TestCase",
    "TestCaseType",
    "Priority",
    "Severity",
    "RiskLevel",
    "ApiConfiguration",
    "AuditLog",
]
