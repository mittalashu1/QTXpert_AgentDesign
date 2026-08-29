from datetime import datetime
from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


ExecutionSuiteType = Literal["smoke", "feature", "regression", "deep_regression"]
ExecutionMode = Literal["automated", "manual"]
ExecutionTargetKind = Literal["web", "android", "ios"]
ExecutionProvider = Literal["playwright", "browserstack", "appium"]

class ExecutionCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl | None = None
    browser: str = Field(default="chromium", pattern="^chromium$")
    test_case_ids: list[UUID] = Field(min_length=1, max_length=100)
    target_kind: ExecutionTargetKind = "web"
    provider: ExecutionProvider = "playwright"
    app_asset_id: UUID | None = None
    device_name: str | None = Field(default=None, max_length=120)
    platform_version: str | None = Field(default=None, max_length=40)
    appium_url: str | None = Field(default=None, max_length=2048)
    appium_app: str | None = Field(default=None, max_length=2048)
    no_reset: bool = False
    auto_grant_permissions: bool = True


class ExecutionPlanImport(BaseModel):
    """Create a reproducible execution plan from one completed Design run."""

    project_id: UUID
    generation_run_id: UUID
    name: str | None = Field(default=None, max_length=255)
    suite_type: ExecutionSuiteType = "regression"


class ExecutionPlanCaseSelection(BaseModel):
    id: UUID
    selected: bool
    execution_mode: ExecutionMode = "automated"


class ExecutionPlanCasesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[ExecutionPlanCaseSelection] = Field(min_length=1, max_length=500)


class ExecutionPlanPreflight(BaseModel):
    target_kind: ExecutionTargetKind = "web"
    provider: ExecutionProvider = "playwright"
    base_url: HttpUrl | None = None
    app_asset_id: UUID | None = None
    device_name: str | None = Field(default=None, max_length=120)
    platform_version: str | None = Field(default=None, max_length=40)
    appium_url: str | None = Field(default=None, max_length=2048)
    appium_app: str | None = Field(default=None, max_length=2048)
    no_reset: bool = False
    auto_grant_permissions: bool = True


class ExecutionPlanExecute(BaseModel):
    target_kind: ExecutionTargetKind = "web"
    provider: ExecutionProvider = "playwright"
    base_url: HttpUrl | None = None
    app_asset_id: UUID | None = None
    device_name: str | None = Field(default=None, max_length=120)
    platform_version: str | None = Field(default=None, max_length=40)
    appium_url: str | None = Field(default=None, max_length=2048)
    appium_app: str | None = Field(default=None, max_length=2048)
    no_reset: bool = False
    auto_grant_permissions: bool = True
    name: str | None = Field(default=None, max_length=255)
    browser: Literal["chromium"] = "chromium"


class ExecutionPlanRerun(BaseModel):
    source_execution_id: UUID
    name: str | None = Field(default=None, max_length=255)

class DefectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1, max_length=10000)
    severity: str = Field(pattern="^(blocker|critical|major|minor|trivial)$")

class DefectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    defect_key: str
    title: str
    severity: str
    status: str

class ExecutionResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    test_case_id: UUID
    execution_plan_case_id: UUID | None = None
    test_case_key: str
    scenario: str
    status: str
    duration_ms: int | None
    error_message: str | None
    evidence: dict | None
    defects: list[DefectOut] = Field(default_factory=list)

class ExecutionRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    execution_plan_id: UUID | None = None
    name: str
    status: str
    browser: str
    base_url: str | None
    target_kind: str = "web"
    provider: str = "playwright"
    app_asset_id: UUID | None = None
    device_name: str | None = None
    platform_version: str | None = None
    total_tests: int
    passed_tests: int
    failed_tests: int
    blocked_tests: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    results: list[ExecutionResultOut] = Field(default_factory=list)


class ExecutionPlanCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_test_case_id: UUID | None
    selection_order: int
    selected: bool
    execution_mode: ExecutionMode
    readiness: str
    blocker_reason: str | None
    test_case_key: str
    requirement_traceability: str | None
    test_type: str
    scenario: str
    objective: str
    priority: str
    severity: str
    preconditions: str | None
    test_data: dict | None
    steps: list
    expected_result: str
    post_conditions: str | None
    is_automation_candidate: bool
    automation_type: str | None
    risk_level: str


class ExecutionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_generation_run_id: UUID | None
    name: str
    suite_type: ExecutionSuiteType
    status: str
    source_title: str | None
    source_created_at: datetime | None
    created_at: datetime
    updated_at: datetime
    total_cases: int
    selected_cases: int
    selected_automated_cases: int
    ready_cases: int
    blocked_cases: int
    cases: list[ExecutionPlanCaseOut] = Field(default_factory=list)

class DashboardSummary(BaseModel):
    requirements: int
    test_cases: int
    execution_runs: int
    pass_rate: float
    open_defects: int
    automation_candidates: int
    recent_runs: list[ExecutionRunOut]
    # Execution-result counts make the dashboard denominator explicit.  The
    # pass rate is calculated from all test results in the project, including
    # blocked/pending results, rather than only the runs that happened to pass.
    total_execution_tests: int = 0
    executed_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    blocked_tests: int = 0
    skipped_tests: int = 0
    pending_tests: int = 0
