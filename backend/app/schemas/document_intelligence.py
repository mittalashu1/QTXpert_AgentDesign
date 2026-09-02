"""Pydantic contracts for AI Document Intelligence."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


DocumentProfile = Literal["general", "banking", "retail", "saas", "government"]
FindingStatus = Literal["open", "accepted", "rejected", "resolved", "needs_clarification"]


class DocumentAnalyzeRequest(BaseModel):
    project_id: UUID
    asset_ids: list[UUID] = Field(min_length=1, max_length=30)
    profile: DocumentProfile = "general"
    additional_context: str = Field(default="", max_length=8000)


class DocumentFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    asset_id: Optional[UUID]
    finding_key: str
    category: str
    severity: str
    confidence: float
    title: str
    description: str
    testing_impact: Optional[str]
    original_text: Optional[str]
    suggested_refinement: Optional[str]
    evidence: Optional[list]
    status: str
    resolution_note: Optional[str]
    created_at: datetime
    updated_at: datetime


class DocumentAnalysisRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    requested_by_id: UUID
    status: str
    profile: str
    asset_ids: list
    additional_context: Optional[str] = None
    document_inventory: Optional[list]
    knowledge_model: Optional[dict]
    scores: Optional[dict]
    missing_documents: Optional[list]
    recommendations: Optional[list]
    readiness_score: int
    readiness_status: str
    summary: Optional[str]
    error_message: Optional[str]
    published_requirement_id: Optional[UUID]
    findings: list[DocumentFindingOut] = []
    created_at: datetime
    updated_at: datetime


class FindingReviewRequest(BaseModel):
    status: FindingStatus
    resolution_note: Optional[str] = Field(default=None, max_length=4000)
    suggested_refinement: Optional[str] = Field(default=None, max_length=8000)


class PublishIntelligenceResponse(BaseModel):
    run_id: UUID
    requirement_id: UUID
    title: str
    message: str


class DocumentContextOut(BaseModel):
    """A bounded, redacted context excerpt safe to attach to another module."""

    run_id: UUID
    project_id: UUID
    status: str
    profile: str
    context: str
    asset_ids: list[UUID] = Field(default_factory=list)
    summary: Optional[str] = None
    published_requirement_id: Optional[UUID] = None
    open_finding_count: int = 0
    critical_finding_count: int = 0
    high_finding_count: int = 0


class DocumentTraceabilityGenerationOut(BaseModel):
    id: UUID
    status: str
    title: Optional[str] = None
    test_case_count: int = 0
    created_at: datetime


class DocumentTraceabilityOut(BaseModel):
    """Downstream delivery counters for one immutable document analysis."""

    run_id: UUID
    project_id: UUID
    status: str
    published_requirement_id: Optional[UUID] = None
    finding_count: int = 0
    open_finding_count: int = 0
    critical_finding_count: int = 0
    high_finding_count: int = 0
    generated_test_case_count: int = 0
    generation_runs: list[DocumentTraceabilityGenerationOut] = Field(default_factory=list)
    execution_plan_count: int = 0
    execution_run_count: int = 0
    active_execution_count: int = 0
    executed_test_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    pending_test_count: int = 0
    skipped_test_count: int = 0
    next_actions: list[str] = Field(default_factory=list)


class DocumentGenerateTestsRequest(BaseModel):
    generation_profile: Literal["smoke", "feature", "regression", "deep_regression"] = "feature"
    test_set_title: Optional[str] = Field(default=None, max_length=500)


class DocumentGenerateTestsResponse(BaseModel):
    run_id: UUID
    generation_run_id: UUID
    requirement_id: UUID
    status: str
    title: Optional[str] = None
    message: str

