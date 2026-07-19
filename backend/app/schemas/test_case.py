from datetime import datetime
from typing import Any, List, Optional
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
    status: RunStatus
    llm_provider: str
    llm_model: str
    requirement_summary: Optional[str]
    business_rules: Optional[list]
    functional_breakdown: Optional[list]
    test_scenarios: Optional[list]
    risk_analysis: Optional[dict[str, Any]]
    processing_time_seconds: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    test_cases: List[TestCaseOut] = Field(default_factory=list)


class ExportRequest(BaseModel):
    generation_run_id: UUID
    format: str = Field(
        description="One of: json, csv, excel, markdown, testrail, zephyr, xray, azure_devops"
    )
