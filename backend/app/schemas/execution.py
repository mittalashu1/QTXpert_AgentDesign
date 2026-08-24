from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class ExecutionCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl
    browser: str = Field(pattern="^chromium$")
    test_case_ids: list[UUID] = Field(min_length=1, max_length=100)

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
    name: str
    status: str
    browser: str
    base_url: str
    total_tests: int
    passed_tests: int
    failed_tests: int
    blocked_tests: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    results: list[ExecutionResultOut] = Field(default_factory=list)

class DashboardSummary(BaseModel):
    requirements: int
    test_cases: int
    execution_runs: int
    pass_rate: float
    open_defects: int
    automation_candidates: int
    recent_runs: list[ExecutionRunOut]

