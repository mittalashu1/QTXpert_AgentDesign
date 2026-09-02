from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.database.models.generation_run import RunStatus
from app.database.models.test_case import Priority, RiskLevel, Severity, TestCaseType


class GenerateTestCasesRequest(BaseModel):
    project_id: UUID
    requirement_ids: List[UUID] = Field(
        default_factory=list,
        description="If empty, all requirements in the project are used.",
    )
    llm_provider_override: Optional[str] = None
    generation_profile: Literal["smoke", "feature", "regression", "deep_regression"] = "feature"
    test_set_title: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional user-facing title derived from the source document or query.",
    )
    source_document_analysis_id: Optional[UUID] = Field(
        default=None,
        description="Optional completed Document Intelligence run that supplied the source requirement.",
    )


class TestCaseUpdate(BaseModel):
    """The fields exposed by the Design Agent's inline editor."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    scenario: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1)
    preconditions: Optional[str] = None
    steps: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)


class UpdateGenerationRunRequest(BaseModel):
    """Replace the editable fields on an existing run without creating a run."""

    model_config = ConfigDict(extra="forbid")

    test_cases: List[TestCaseUpdate] = Field(default_factory=list)


class GenerationRunTitleUpdate(BaseModel):
    """Rename a saved Test Design run without changing or regenerating its suite."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)


class TestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    test_case_key: str
    requirement_traceability: Optional[str]
    test_type: TestCaseType
    scenario: str
    objective: str
    priority: Priority
    severity: Severity
    preconditions: Optional[str]
    test_data: Optional[dict[str, Any]]
    steps: list
    expected_result: str
    post_conditions: Optional[str]
    is_automation_candidate: bool
    automation_type: Optional[str]
    risk_level: RiskLevel


class GenerationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_document_analysis_id: Optional[UUID] = None
    status: RunStatus
    llm_provider: str
    llm_model: str
    generation_profile: str
    title: Optional[str] = None
    requirement_summary: Optional[str]
    business_rules: Optional[list]
    functional_breakdown: Optional[list]
    test_scenarios: Optional[list]
    risk_analysis: Optional[dict[str, Any]]
    processing_time_seconds: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    test_cases: List[TestCaseOut] = Field(default_factory=list)


class GenerationRunSummaryOut(BaseModel):
    """Lightweight run metadata for history rails and selectors.

    The full generated test cases are intentionally excluded; clients fetch one
    GenerationRunOut only when the user opens a specific run.
    """

    id: UUID
    project_id: UUID
    source_document_analysis_id: Optional[UUID] = None
    status: RunStatus
    llm_provider: str
    llm_model: str
    generation_profile: str
    title: Optional[str] = None
    requirement_summary: Optional[str] = None
    first_scenario: Optional[str] = None
    test_case_count: int = 0
    created_at: datetime


class ExportRequest(BaseModel):
    generation_run_id: UUID
    format: str = Field(
        description="One of: json, csv, excel, markdown, testrail, zephyr, xray, azure_devops"
    )
