"""Schemas for the unified QTXpert Autopilot target and evidence contract."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


AutopilotTestBucket = Literal[
    "installation",
    "page_level",
    "functional",
    "functional_positive",
    "functional_negative",
    "uat",
    "ui",
    "ui_positive",
    "ui_negative",
    "accessibility",
    "integration",
    "sit",
    "performance",
    "security",
    "compatibility",
    "resilience",
    "permissions",
    "regression",
]
AutopilotTargetKind = Literal["android", "ios", "web"]
AutopilotProvider = Literal["browserstack", "appium", "playwright"]

# The phase is intentionally separate from the legacy ``status`` field.  The
# latter is a transport/storage status used by older clients, while this
# contract describes the user-visible autonomous workflow and can be resumed
# safely after a worker restart.
AutopilotPhase = Literal[
    "draft",
    "preflight",
    "context_ready",
    "plan_pending_review",
    "plan_approved",
    "exploring",
    "cases_pending_review",
    "cases_approved",
    "execution_ready",
    "running",
    "completed",
    "partial",
    "blocked",
    "failed",
]


AutopilotInputCategory = Literal[
    "credential",
    "environment",
    "test_data",
    "approval",
    "acceptance",
    "integration",
]
AutopilotInputStatus = Literal["pending", "provided", "validated", "skipped", "saved", "random"]
AutopilotInputDecision = Literal["provide", "skip", "reuse", "random"]
AutopilotRandomKind = Literal["number", "digits", "text", "email", "phone", "date", "amount"]


AutopilotScopeSourceKind = Literal[
    "profile",
    "user_context",
    "document",
    "internet",
    "target",
    "runtime",
    "system",
]


class AutopilotScopeSource(BaseModel):
    """A safe, human-readable source used by the scope compiler.

    Sources contain references and short summaries only.  They deliberately do
    not carry document bodies, credentials or runtime secrets.
    """

    # ``source_id`` is stable within a run and is safe to expose in reports.
    # It lets plan items and generated cases point back to the exact source
    # without copying document bodies or secret values.
    source_id: str = ""
    kind: AutopilotScopeSourceKind
    label: str
    reference: Optional[str] = None
    summary: str = ""
    observed: bool = False
    # Confidence describes the source signal, not the truth of an unobserved
    # claim. ``used`` and ``influenced_*`` make the context panel auditable.
    confidence: float = Field(default=0.5, ge=0, le=1)
    trust_level: Literal["high", "medium", "low"] = "medium"
    used: bool = False
    influenced_plan_items: List[str] = Field(default_factory=list)
    influenced_test_ids: List[str] = Field(default_factory=list)
    retrieved_at: Optional[str] = None


class AutopilotScopeSection(BaseModel):
    """One editable scope section kept in its original evidence context."""

    key: str
    title: str
    summary: str
    source: AutopilotScopeSourceKind = "system"
    source_refs: List[str] = Field(default_factory=list)
    status: Literal["planned", "observed", "deferred", "not_applicable"] = "planned"
    requested: bool = False
    editable: bool = True


class AutopilotScope(BaseModel):
    """Concise scope contract shared by context, analysis and reports.

    The scope compiler translates technical evidence into plain-language
    coverage while retaining the original document sections, change signals
    and source references for auditability.
    """

    schema_version: str = "qtx-scope/1.0"
    summary: str = ""
    target: str = ""
    functional_scope: List[str] = Field(default_factory=list)
    non_functional_scope: List[str] = Field(default_factory=list)
    requested_test_types: List[str] = Field(default_factory=list)
    # Journeys explicitly named in the editable brief remain visible even
    # before Runtime Discovery can confirm that the target contains them.
    requested_journeys: List[AutopilotScopeSection] = Field(default_factory=list)
    change_impact: List[str] = Field(default_factory=list)
    # Document-only sections stay separate from the complete scope index so
    # the UI can show both the source documents and the runtime-observed map
    # without conflating them.
    document_sections: List[AutopilotScopeSection] = Field(default_factory=list)
    scope_sections: List[AutopilotScopeSection] = Field(default_factory=list)
    sources: List[AutopilotScopeSource] = Field(default_factory=list)
    authentication_gate: str = (
        "Runtime Discovery must observe a real sign-in form before authenticated execution."
    )
    runtime_observed: bool = False
    login_observed: bool = False
    editable: bool = True


class AutopilotRandomSpec(BaseModel):
    """A bounded, non-secret recipe for generating synthetic test data."""

    kind: AutopilotRandomKind = "text"
    length: int = Field(default=12, ge=1, le=256)
    minimum: Optional[float] = Field(default=None, ge=-1_000_000_000_000, le=1_000_000_000_000)
    maximum: Optional[float] = Field(default=None, ge=-1_000_000_000_000, le=1_000_000_000_000)
    seed: Optional[str] = Field(default=None, max_length=128)


class AutopilotInputSubmission(BaseModel):
    """One user decision for a checkpoint input.

    ``value`` is accepted only on this write boundary.  The API encrypts it
    immediately and never includes it in a response, log message or job
    snapshot.
    """

    key: str = Field(min_length=1, max_length=120)
    decision: AutopilotInputDecision = "provide"
    value: Optional[str] = Field(default=None, max_length=4000)
    save_for_reuse: bool = False
    random_spec: Optional[AutopilotRandomSpec] = None


class AutopilotSavedInput(BaseModel):
    """Safe metadata for a saved encrypted input; never contains its value."""

    key: str
    label: str
    category: AutopilotInputCategory
    decision: AutopilotInputDecision
    save_for_reuse: bool = True
    has_value: bool = False
    generator_kind: Optional[AutopilotRandomKind] = None
    source: Literal["plan", "runtime", "user"] = "user"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    expires_at: Optional[str] = None


class AutopilotInputRequest(BaseModel):
    """A safe, auditable checkpoint request.

    Direct values may be submitted only through the write-only checkpoint
    boundary and are encrypted immediately; this response model contains no
    value, token, password or OTP.
    """

    key: str
    label: str
    category: AutopilotInputCategory
    reason: str
    required_for: List[str] = Field(default_factory=list)
    sensitive: bool = False
    status: AutopilotInputStatus = "pending"
    reference_present: bool = False
    # Runtime discovery may add an exact field/control without ever exposing
    # the value entered into it. These fields are references only (for
    # example, a vault key or synthetic-data fixture name).
    source: Literal["plan", "runtime"] = "plan"
    screen_id: Optional[str] = None
    control_id: Optional[str] = None
    field_type: Optional[str] = None
    input_hint: Optional[Literal["username", "password", "otp", "text"]] = None
    locator: Optional[str] = None
    # Human-facing guidance is kept separate from the stable label/key so the
    # checkpoint can explain exactly what the user should provide.  These are
    # safe metadata only; submitted values still travel through the encrypted
    # write-only input boundary.
    question: Optional[str] = None
    placeholder: Optional[str] = None
    format_hint: Optional[str] = None
    credential_bundle: bool = False
    # Evidence context for a checkpoint. These labels let the UI point to the
    # exact observed journey/page/field instead of showing an opaque test ID.
    journey: Optional[str] = None
    page_label: Optional[str] = None
    page_url: Optional[str] = None
    field_label: Optional[str] = None
    # Opaque repository evidence references for the exact screen that
    # surfaced this checkpoint. They are safe to return; the UI downloads the
    # image through the authenticated uploads endpoint when the user opens it.
    screenshot_asset_id: Optional[UUID] = None
    page_source_asset_id: Optional[UUID] = None
    probe_guidance: List[Dict[str, str]] = Field(default_factory=list)


class AutopilotDataProbe(BaseModel):
    """A non-secret positive/negative/boundary strategy for one field."""

    kind: Literal["positive", "negative", "boundary"]
    label: str
    guidance: str


class AutopilotTestProvenance(BaseModel):
    """A compact source trail explaining why a test exists."""

    kind: AutopilotScopeSourceKind
    label: str
    reference: Optional[str] = None
    observed: bool = False
    confidence: float = Field(default=0.5, ge=0, le=1)
    source_id: Optional[str] = None


class AutopilotPlanItem(BaseModel):
    """One editable, source-backed item in the generated coverage plan."""

    id: str
    title: str
    description: str
    test_type: str = "functional"
    status: Literal["planned", "running", "completed", "blocked", "skipped"] = "planned"
    source_refs: List[str] = Field(default_factory=list)
    requirement_refs: List[str] = Field(default_factory=list)
    risk: Literal["critical", "high", "medium", "low"] = "medium"
    estimated_case_count: int = Field(default=0, ge=0)
    expected_output: str = ""
    actual_output: Optional[str] = None
    agent: str = "Autopilot planner"
    depends_on: List[str] = Field(default_factory=list)
    approval_required: bool = False
    editable: bool = True


class AutopilotGenerationPlan(BaseModel):
    """Versioned plan shown to the user before exploration and execution."""

    schema_version: str = "qtx-autopilot-plan/1.0"
    plan_id: str
    job_id: str
    version: int = Field(default=1, ge=1)
    status: Literal["draft", "pending_review", "approved", "superseded"] = "pending_review"
    target_kind: AutopilotTargetKind = "android"
    summary: str = ""
    items: List[AutopilotPlanItem] = Field(default_factory=list)
    requested_test_types: List[str] = Field(default_factory=list)
    context_source_count: int = Field(default=0, ge=0)
    document_section_count: int = Field(default=0, ge=0)
    runtime_gate: str = (
        "Explore the supplied target first; authenticated execution starts only after an observed sign-in is approved."
    )
    approval_required: bool = True
    editable: bool = True
    generated_at: str = ""


class AutopilotApplicationMap(BaseModel):
    """Durable projection of the observed application/page graph."""

    schema_version: str = "qtx-application-map/1.0"
    map_id: str
    job_id: str
    target_kind: AutopilotTargetKind = "android"
    target_identity: Optional[str] = None
    version: int = Field(default=1, ge=1)
    generated_at: str = ""
    login_observed: bool = False
    screens: List["DiscoveredScreen"] = Field(default_factory=list)
    transitions: List["DiscoveredTransition"] = Field(default_factory=list)
    controls_count: int = Field(default=0, ge=0)
    # These are references/observations only. Values such as passwords and
    # session tokens are never part of the map.
    authentication_boundaries: List[str] = Field(default_factory=list)
    validation_behaviors: List[str] = Field(default_factory=list)
    observation_refs: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    coverage_notes: List[str] = Field(default_factory=list)


class AutopilotPlanUpdateRequest(BaseModel):
    """User-editable plan fields; secrets and runtime values are excluded."""

    summary: Optional[str] = Field(default=None, max_length=4000)
    items: Optional[List[AutopilotPlanItem]] = Field(default=None, max_length=500)
    requested_test_types: Optional[List[str]] = Field(default=None, max_length=40)


class AutopilotCaseReviewUpdateRequest(BaseModel):
    """Review decision for one grounded case before execution."""

    decision: Literal["approve", "defer", "skip"]
    note: Optional[str] = Field(default=None, max_length=1000)


class AutopilotCaseApprovalRequest(BaseModel):
    """Approve grounded cases for hand-off to the shared Test Case library."""

    case_ids: List[str] = Field(default_factory=list, max_length=5000)
    approve_all: bool = False
    note: Optional[str] = Field(default=None, max_length=1000)


class AutopilotCaseLibraryResult(BaseModel):
    """Result of an idempotent Autopilot-to-Test-Design library hand-off."""

    job_id: str
    generation_run_id: UUID
    persisted_case_ids: List[UUID] = Field(default_factory=list)
    persisted_count: int = 0
    skipped_case_ids: List[str] = Field(default_factory=list)
    message: str = "Approved cases are available in the shared Test Case library."


class AutopilotTest(BaseModel):
    id: str
    suite: str
    title: str
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    severity: Literal["blocker", "critical", "major", "minor", "trivial"] = "major"
    risk_level: Literal["high", "medium", "low"] = "medium"
    objective: str
    steps: List[str] = Field(default_factory=list)
    expected: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    postconditions: List[str] = Field(default_factory=list)
    cleanup_requirements: List[str] = Field(default_factory=list)
    autonomous: bool = True
    destructive: bool = False
    source: Literal["deterministic", "ai"] = "deterministic"
    # A bucket describes the kind of coverage, independently from whether the
    # case is executable now. This keeps the generated plan complete while
    # allowing the runner/report to remain evidence-led.
    bucket: AutopilotTestBucket = "functional"
    requires_auth: bool = False
    requires_test_data: bool = False
    # ``autonomous_candidate`` marks an evidence-scoped case that can use a
    # bounded synthetic value (or an observed read-only assertion) during the
    # first pass.  It is deliberately separate from ``autonomous``: a case
    # can be designed for automation while still needing credentials, an
    # oracle or explicit approval before it is eligible to run.
    autonomous_candidate: bool = False
    synthetic_data_strategy: Optional[str] = None
    dependency: Optional[str] = None
    evidence_required: List[str] = Field(default_factory=list)
    # Human-facing grouping metadata derived only from observed target
    # evidence. URLs and opaque screen IDs stay out of the title.
    journey: Optional[str] = None
    page_label: Optional[str] = None
    page_url: Optional[str] = None
    data_probes: List[AutopilotDataProbe] = Field(default_factory=list)
    provenance: List[AutopilotTestProvenance] = Field(default_factory=list)
    requirement_refs: List[str] = Field(default_factory=list)
    source_refs: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    safety_classification: Literal["safe", "review", "blocked"] = "safe"
    observation_refs: List[str] = Field(default_factory=list)
    test_data_refs: List[str] = Field(default_factory=list)
    duplicate_of: Optional[str] = None
    duplicate_status: Literal["unique", "similar", "duplicate", "unknown"] = "unknown"


class AutopilotAnalysis(BaseModel):
    job_id: str
    filename: str
    platform: AutopilotTargetKind = "android"
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    status: Literal["analyzed", "analysis_partial"] = "analyzed"
    app_name: Optional[str] = None
    package_name: Optional[str] = None
    version_name: Optional[str] = None
    version_code: Optional[str] = None
    min_sdk: Optional[str] = None
    target_sdk: Optional[str] = None
    main_activity: Optional[str] = None
    activities: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    receivers: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    file_count: int = 0
    size_bytes: int = 0
    sha256: str
    debuggable: Optional[bool] = None
    inferred_domain: str = "General mobile application"
    app_summary: str = ""
    critical_journeys: List[str] = Field(default_factory=list)
    clarification_questions: List[str] = Field(default_factory=list)
    tests: List[AutopilotTest] = Field(default_factory=list)
    release_risks: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    capabilities: Dict[str, bool] = Field(default_factory=dict)
    # Generation provenance is kept next to the plan so clients can explain
    # what was produced without reverse-engineering the test list.
    coverage_counts: Dict[str, int] = Field(default_factory=dict)
    generation_policy: List[str] = Field(default_factory=list)
    input_summary: List[str] = Field(default_factory=list)
    # Provenance is explicit so the UI/report can distinguish target evidence,
    # the selected business context and optional LLM enrichment.
    context_considered: Optional[bool] = None
    ai_enrichment_used: Optional[bool] = None
    analysis_basis: List[str] = Field(default_factory=list)
    # Repository documentation attached to this run. The IDs make the source
    # of the context auditable without copying document contents into reports.
    document_asset_ids: List[UUID] = Field(default_factory=list)
    document_analysis_run_id: Optional[UUID] = None
    # Input collection is a first-class checkpoint.  It is populated from the
    # generated plan without exposing credentials or test-data values.
    checkpoint_stage: str = "complete"
    input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    # The compiled scope is deliberately stored inside the versioned analysis
    # JSON so older database rows remain readable without a migration.
    scope: AutopilotScope = Field(default_factory=AutopilotScope)
    phase: AutopilotPhase = "context_ready"
    generation_plan: Optional[AutopilotGenerationPlan] = None
    application_map: Optional[AutopilotApplicationMap] = None
    context_pack_version: str = "qtx-context/1.0"
    case_reviews: Dict[str, str] = Field(default_factory=dict)


ReportCheckStatus = Literal["pass", "fail", "warning", "pending", "not_assessed"]


class AutopilotProfileOption(BaseModel):
    """A selectable business/QA profile used to seed the brief context."""

    id: str
    name: str
    description: str
    brief_context: str


class AutopilotContextRequest(BaseModel):
    """Request for the guided business-context writer used by Autopilot."""

    mode: Literal["default", "generate", "improve"] = "generate"
    profile_id: str = Field(default="uae_fintech", max_length=80)
    current_context: str = Field(default="", max_length=8000)
    application_name: Optional[str] = Field(default=None, max_length=200)
    package_name: Optional[str] = Field(default=None, max_length=300)
    platform: str = Field(default="Android", max_length=80)
    target_url: Optional[str] = Field(default=None, max_length=2048)
    build_name: Optional[str] = Field(default=None, max_length=500)
    observed_metadata: Dict[str, Any] = Field(default_factory=dict)
    focus: Optional[str] = Field(default=None, max_length=500)
    # Internet research is bounded, public and read-only.  It contributes
    # hypotheses and plain-language feature signals; it is never execution
    # evidence and can be disabled by an API client that needs an offline run.
    use_internet: bool = True
    document_asset_ids: List[UUID] = Field(default_factory=list, max_length=20)
    document_analysis_run_id: Optional[UUID] = None
    # The server may supply a redacted Document Intelligence hand-off here.
    # Direct clients should leave it empty; document IDs remain the durable
    # lineage reference.
    document_context: str = Field(default="", max_length=8000)


class AutopilotContextResponse(BaseModel):
    context: str
    source: Literal["default", "ai", "fallback"]
    profile_id: str = "uae_fintech"
    warning: Optional[str] = None
    scope: AutopilotScope = Field(default_factory=AutopilotScope)
    research_sources: List[AutopilotScopeSource] = Field(default_factory=list)


class AutopilotReportCheck(BaseModel):
    key: str
    title: str
    status: ReportCheckStatus = "pending"
    summary: str
    dependency: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    recommendation: Optional[str] = None


class AutopilotReportRisk(BaseModel):
    risk_id: str
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    likelihood: Literal["high", "medium", "low"]
    impact: Literal["critical", "high", "medium", "low"]
    status: Literal["open", "mitigated", "pending_validation", "accepted"] = "open"
    evidence: str
    mitigation: str


class AutopilotApplicationOverview(BaseModel):
    name: str
    publisher: str = "Not specified"
    platform: str = "Android"
    package_name: str = "Not identified"
    version: str = "Not identified"
    target_market: str = "Not specified"
    regulatory_bodies: List[str] = Field(default_factory=list)
    core_features: List[str] = Field(default_factory=list)


class AutopilotReportMetrics(BaseModel):
    designed_test_cases: int = 0
    executed_test_cases: Optional[int] = None
    passed_count: int = 0
    failed_count: int = 0
    blocked_count: int = 0
    skipped_count: int = 0
    pass_rate: Optional[float] = None
    defect_count: Optional[int] = None
    environment: List[str] = Field(default_factory=list)
    evidence_state: str = "Runtime execution has not been recorded."


class AutopilotReportEvidenceAsset(BaseModel):
    """A durable evidence link surfaced by the Test and Audit Report."""

    asset_id: UUID
    filename: str
    kind: Literal["screenshot", "page_source", "video", "other"] = "other"
    bucket: Optional[AutopilotTestBucket] = None
    test_id: Optional[str] = None
    title: Optional[str] = None
    scope: Literal["test", "suite", "smoke"] = "test"


class AutopilotTestAuditReport(BaseModel):
    """Executive release-readiness report derived from evidence and context."""

    schema_version: str = "qtx-audit-report/1.0"
    generated_at: str
    report_title: str = "Test and Audit Report"
    prepared_for: str = "Executive management"
    role: str = "Fintech QA Lead and Compliance Auditor"
    recommendation: Literal["GO", "GO_WITH_CONDITIONS", "NO_GO", "PENDING"] = "PENDING"
    rationale: str
    last_run_at: Optional[str] = None
    executive_findings: List[str] = Field(default_factory=list)
    reported_issues: List[str] = Field(default_factory=list)
    application_overview: AutopilotApplicationOverview
    metrics: AutopilotReportMetrics
    functional_testing: List[AutopilotReportCheck] = Field(default_factory=list)
    non_functional_testing: List[AutopilotReportCheck] = Field(default_factory=list)
    compliance_verification: List[AutopilotReportCheck] = Field(default_factory=list)
    risk_matrix: List[AutopilotReportRisk] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    evidence: List[str] = Field(default_factory=list)
    evidence_assets: List[AutopilotReportEvidenceAsset] = Field(default_factory=list)
    scope: Optional[AutopilotScope] = None


class AutopilotReportDeletionResult(BaseModel):
    """Audit-safe result returned after deleting one report tab's data."""

    job_id: str
    deleted: Dict[str, int] = Field(default_factory=dict)
    preserved_upload_ids: List[UUID] = Field(default_factory=list)
    preserved_shared_input_records: int = 0
    local_report_data_removed: bool = False
    local_source_preserved: bool = False
    message: str = "The report data was deleted; repository uploads were preserved."


class AutopilotJobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    package_name: Optional[str] = None
    app_name: Optional[str] = None
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    profile_id: str = "uae_fintech"
    surface_key: str = ""
    surface_identity: str = ""
    surface_version: int = 1
    repository_asset_id: Optional[UUID] = None
    document_analysis_run_id: Optional[UUID] = None
    created_at: str


class AutopilotSurface(BaseModel):
    """One isolated Test & Audit Report tab for a profile/target/build scope.

    ``surface_key`` remains the stable duplicate-detection key for backwards
    compatibility. ``report_tab_key`` is unique per active analysis version so
    choosing ``new`` creates a separate report tab instead of replacing the
    existing one in the UI.
    """

    report_tab_key: str = ""
    surface_key: str
    surface_identity: str
    profile_id: str = "uae_fintech"
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    filename: str = ""
    latest_job_id: str
    latest_status: str
    surface_version: int = 1
    version_count: int = 1
    latest_created_at: str
    latest_updated_at: str
    is_current: bool = True


class AutopilotJobStatus(BaseModel):
    job_id: str
    filename: str
    status: Literal["uploaded", "analyzing", "waiting_for_input", "analyzed", "failed", "superseded"]
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    profile_id: str = "uae_fintech"
    report_tab_key: str = ""
    surface_key: str = ""
    surface_identity: str = ""
    surface_version: int = 1
    repository_asset_id: Optional[UUID] = None
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    created_at: str
    updated_at: str
    context: str = ""
    document_asset_ids: List[UUID] = Field(default_factory=list)
    document_analysis_run_id: Optional[UUID] = None
    artifact_available: bool = True
    error: Optional[str] = None
    analysis: Optional[AutopilotAnalysis] = None
    checkpoint_stage: str = "queued"
    checkpoint_message: Optional[str] = None
    input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    phase: AutopilotPhase = "draft"
    phase_updated_at: Optional[str] = None
    generation_plan: Optional[AutopilotGenerationPlan] = None
    application_map: Optional[AutopilotApplicationMap] = None


class AutopilotProviderStatus(BaseModel):
    browserstack_configured: bool = False
    custom_appium_available: bool = False
    playwright_available: bool = True
    custom_appium_reason: Optional[str] = None
    custom_appium_url: Optional[str] = None
    recommended_provider: AutopilotProvider = "appium"


class AutopilotSetupUpdateRequest(BaseModel):
    """Non-secret references used to resolve deferred Autopilot tests."""

    credential_reference: str = Field(default="", max_length=300)
    account_role: str = Field(default="", max_length=160)
    environment_name: str = Field(default="", max_length=160)
    environment_url: str = Field(default="", max_length=1000)
    test_data_reference: str = Field(default="", max_length=500)
    reset_hook_reference: str = Field(default="", max_length=500)
    acceptance_criteria_reference: str = Field(default="", max_length=500)
    api_oracle_reference: str = Field(default="", max_length=500)
    navigation_notes: str = Field(default="", max_length=4000)
    safe_authentication_approved: bool = False
    # Approval applies to any number of observed cases; the plan itself is
    # finite because it is derived from the target graph, not a fixed quota.
    approved_test_ids: List[str] = Field(default_factory=list)
    # Optional per-control references let a user map a discovered username,
    # password, search or test-data field to a vault/fixture without sending
    # the actual value to QTXpert.
    runtime_input_references: Dict[str, str] = Field(default_factory=dict)
    # Direct values are accepted only for this request and are encrypted by
    # the API before persistence. They are intentionally excluded from all
    # response schemas and job manifests.
    input_submissions: List[AutopilotInputSubmission] = Field(default_factory=list, max_length=50)


class AutopilotSetupProfile(AutopilotSetupUpdateRequest):
    """Durable setup metadata; passwords and tokens are intentionally excluded."""

    job_id: str
    updated_at: Optional[str] = None
    provided_fields: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    runtime_input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    input_decisions: Dict[str, AutopilotInputDecision] = Field(default_factory=dict)
    saved_inputs: List[AutopilotSavedInput] = Field(default_factory=list)
    skipped_input_keys: List[str] = Field(default_factory=list)
    random_input_keys: List[str] = Field(default_factory=list)
    checkpoint_stage: str = "input_collection"
    checkpoint_message: Optional[str] = None
    last_validated_at: Optional[str] = None


class AutopilotResumeRequest(BaseModel):
    """Continue a paused analysis after setup references were confirmed."""

    confirm_saved_inputs: bool = True
    run_runtime_discovery: bool = False
    # When enabled, a successful safe discovery is followed by the bounded
    # read-only suite automatically.  Payments, OTP, destructive and other
    # approval-gated cases are never included by this switch.
    auto_run_safe_suite: bool = True
    # Optional safe-discovery preferences used when the server chains resume
    # directly into discovery. They contain no credentials or field values.
    discovery_provider: Optional[AutopilotProvider] = None
    discovery_device_name: Optional[str] = Field(default=None, max_length=160)
    discovery_platform_version: Optional[str] = Field(default=None, max_length=80)
    discovery_appium_url: Optional[str] = Field(default=None, max_length=2048)
    discovery_appium_app: Optional[str] = Field(default=None, max_length=2048)


class DiscoveryLocator(BaseModel):
    strategy: Literal["accessibility_id", "id", "xpath", "css"]
    value: str
    confidence: float = Field(ge=0, le=1)


class QTXIRStep(BaseModel):
    action: Literal[
        "launch_app",
        "launch",
        "background_app",
        "restore_app",
        "scroll",
        "swipe",
        "capture_evidence",
        "inspect_ui",
        "static_assertion",
        "permission_flow",
        "permission_grant",
        "permission_deny",
        "network_condition",
        "intent",
        "wait_for_state",
        "tap",
        "click",
        "fill",
        "clear",
        "select",
        "press",
        "navigate",
        "assert_visible",
        "assert_text",
        "assert_url",
        "request_json",
        "request",
        "assert_json",
        "reset",
        "reset_state",
        "assert_validation_feedback",
        "assert_value",
        "assert_attribute",
    ]
    description: str
    target: Optional[str] = None
    value: Optional[str] = None
    # Stable encrypted-input reference.  The actual value is resolved only in
    # the runner and is never included in the generated IR or API response.
    input_key: Optional[str] = None
    safe_for_autopilot: bool = True
    screen_id: Optional[str] = None
    locator_strategy: Optional[Literal["accessibility_id", "id", "xpath", "css"]] = None
    locator_value: Optional[str] = None
    locator_confidence: Optional[float] = Field(default=None, ge=0, le=1)
    # Additional deterministic locators observed for the same control. The
    # runner may try these only after the preferred locator misses; no new
    # selector is generated or guessed at execution time.
    locator_fallbacks: List[DiscoveryLocator] = Field(default_factory=list)
    timeout_ms: Optional[int] = Field(default=None, ge=0, le=120_000)
    retry_count: int = Field(default=0, ge=0, le=5)
    safety_classification: Literal["safe", "review", "blocked"] = "safe"
    observation_ref: Optional[str] = None
    value_source: Optional[Literal["literal_non_secret", "encrypted_input", "generated_fixture", "environment", "observed"]] = None
    assertion: Optional[str] = None
    on_error: Optional[Literal["stop", "continue", "capture_and_stop", "request_input"]] = "capture_and_stop"


class QTXTestIR(BaseModel):
    schema_version: str = "qtx-ir/0.2"
    test_id: str
    title: str
    suite: str
    priority: Literal["critical", "high", "medium", "low"]
    readiness: Literal["executable", "discovery_required", "approval_required"]
    source: Literal["deterministic", "ai"]
    bucket: AutopilotTestBucket = "functional"
    requires_auth: bool = False
    requires_test_data: bool = False
    autonomous_candidate: bool = False
    synthetic_data_strategy: Optional[str] = None
    dependency: Optional[str] = None
    promoted_by_discovery: bool = False
    readiness_reason: Optional[str] = None
    steps: List[QTXIRStep] = Field(default_factory=list)
    assertions: List[str] = Field(default_factory=list)
    appium_python: str = ""
    journey: Optional[str] = None
    page_label: Optional[str] = None
    page_url: Optional[str] = None
    data_probes: List[AutopilotDataProbe] = Field(default_factory=list)


class AutopilotAutomationBundle(BaseModel):
    job_id: str
    generated_at: str
    framework: str = "QTX Test IR + Appium Python"
    schema_version: str = "qtx-ir/0.2"
    discovery_used: bool = False
    promoted_count: int = 0
    executable_count: int = 0
    discovery_required_count: int = 0
    approval_required_count: int = 0
    bucket_counts: Dict[str, int] = Field(default_factory=dict)
    setup_provided_count: int = 0
    setup_missing_fields: List[str] = Field(default_factory=list)
    tests: List[QTXTestIR] = Field(default_factory=list)


class AutopilotExecutionRequest(BaseModel):
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    provider: AutopilotProvider = "browserstack"
    appium_url: Optional[str] = None
    device_name: str = "Google Pixel 8"
    platform_version: Optional[str] = "14.0"
    appium_app: Optional[str] = Field(
        default=None,
        description="Optional app reference for a custom remote Appium provider. BrowserStack uploads the APK automatically.",
    )
    no_reset: bool = False
    auto_grant_permissions: bool = True
    browser: Literal["chromium"] = "chromium"


class AutopilotExecutionResult(BaseModel):
    execution_id: Optional[UUID] = None
    job_id: str
    status: Literal["passed", "failed", "blocked"]
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    provider: AutopilotProvider
    started_at: str
    finished_at: str
    duration_seconds: float
    device_name: str
    current_package: Optional[str] = None
    current_activity: Optional[str] = None
    screenshot_path: Optional[str] = None
    page_source_path: Optional[str] = None
    screenshot_asset_id: Optional[UUID] = None
    page_source_asset_id: Optional[UUID] = None
    error: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


class AutopilotExecutionRecord(AutopilotExecutionResult):
    """Durable execution result plus the exact request used for reruns."""

    execution_id: UUID
    request: AutopilotExecutionRequest
    created_at: datetime


class AutopilotAnalysisRerunRequest(BaseModel):
    """Start another analysis using the original or a replacement APK."""

    upload_id: Optional[UUID] = None
    target_url: Optional[str] = Field(default=None, max_length=2048)
    context: Optional[str] = Field(default=None, max_length=8000)
    profile_id: str = Field(default="uae_fintech", max_length=80)
    surface_action: Literal["ask", "new", "override"] = "new"
    # A rerun must not silently reuse credentials or seeded data.  The UI asks
    # the user to confirm ``reuse`` (or choose ``fresh``) before submitting.
    setup_action: Literal["ask", "reuse", "fresh"] = "ask"
    document_asset_ids: Optional[List[UUID]] = Field(default=None, max_length=20)
    document_analysis_run_id: Optional[UUID] = Field(
        default=None,
        description="Optional replacement Document Intelligence baseline; omitted preserves the original link.",
    )


class AutopilotDiscoveryRequest(AutopilotExecutionRequest):
    """Bounded safe runtime exploration configuration."""

    # These are safety budgets per pass, not a product-level test-count cap.
    # Continuation is supported by the cursor fields on the result so a large
    # app can be explored over multiple resumable passes.
    max_screens: int = Field(default=12, ge=1, le=40)
    max_actions: int = Field(default=10, ge=0, le=50)
    observe_only: bool = False
    continuation_token: Optional[str] = Field(default=None, max_length=512)


class DiscoveredControl(BaseModel):
    control_id: str
    semantic_label: str
    class_name: str = ""
    text: str = ""
    content_description: str = ""
    resource_id: str = ""
    bounds: str = ""
    clickable: bool = False
    enabled: bool = True
    scrollable: bool = False
    input_capable: bool = False
    input_kind: Optional[str] = None
    input_type: Optional[str] = None
    validation_behavior: Optional[str] = None
    observation_ref: Optional[str] = None
    risk: Literal["safe", "review", "blocked"] = "review"
    risk_reason: Optional[str] = None
    locators: List[DiscoveryLocator] = Field(default_factory=list)


class DiscoveredScreen(BaseModel):
    screen_id: str
    fingerprint: str
    package_name: Optional[str] = None
    activity_name: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    # Human-facing labels are derived from the observed title/activity/controls
    # and never replace the stable screen ID used for replay.
    journey: Optional[str] = None
    page_label: Optional[str] = None
    screenshot_path: Optional[str] = None
    page_source_path: Optional[str] = None
    screenshot_asset_id: Optional[UUID] = None
    page_source_asset_id: Optional[UUID] = None
    state_key: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    observation_ref: Optional[str] = None
    controls: List[DiscoveredControl] = Field(default_factory=list)


class DiscoveredTransition(BaseModel):
    from_screen_id: str
    to_screen_id: str
    control_id: str
    control_label: str
    action: Literal["tap", "back", "scroll"] = "tap"
    duplicate_state: bool = False
    observation_ref: Optional[str] = None


class AutopilotDiscoveryResult(BaseModel):
    job_id: str
    status: Literal["completed", "partial", "blocked", "failed"]
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    provider: AutopilotProvider
    started_at: str
    finished_at: str
    duration_seconds: float
    device_name: str
    observe_only: bool = False
    screen_count: int = 0
    control_count: int = 0
    safe_control_count: int = 0
    blocked_control_count: int = 0
    actions_attempted: int = 0
    stop_reason: str = ""
    # Target validation is separate from Appium session creation.  A provider
    # can accept a session while leaving the Android system UI foreground;
    # these fields make that degraded state explicit and prevent it from being
    # reported as app coverage.
    target_ready: Optional[bool] = None
    target_identity: Optional[str] = None
    target_activity: Optional[str] = None
    target_identity_reason: Optional[str] = None
    # A provider failure must not erase a previously valid map.  When the
    # latest attempt cannot attach to the target, routes keep the last usable
    # screens/transitions and record the failed attempt here for the UI and
    # audit trail.
    last_attempt_status: Optional[Literal["completed", "partial", "blocked", "failed"]] = None
    last_attempt_reason: Optional[str] = None
    last_attempt_at: Optional[str] = None
    screens: List[DiscoveredScreen] = Field(default_factory=list)
    transitions: List[DiscoveredTransition] = Field(default_factory=list)
    # Field-specific, non-secret setup references inferred from the live UI.
    # These are informational until the generic credential/data checkpoint is
    # satisfied; values are never captured from the device.
    input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None
    # A discovery pass is resumable.  The token is opaque to clients and does
    # not contain credentials or page contents.
    exploration_cursor: Optional[str] = None
    can_continue: bool = False
    visited_screen_count: int = Field(default=0, ge=0)
    unvisited_edge_count: int = Field(default=0, ge=0)


class AutopilotSuiteRequest(AutopilotExecutionRequest):
    """Execute safe IR cases and report deferred cases with their dependencies."""

    test_ids: List[str] = Field(default_factory=list)
    buckets: List[AutopilotTestBucket] = Field(default_factory=list, max_length=20)
    # The plan has no arbitrary case-count cap. A safe batch still defaults to
    # 20 so callers can choose an execution size appropriate for their device
    # provider and timeout budget.
    max_tests: int = Field(default=20, ge=1)
    include_deferred: bool = True
    # This is informational for explicitly triggered runs and is also used by
    # the checkpoint-resume worker when it chains discovery into execution.
    auto_run_safe_suite: bool = True


class AutopilotSuiteTestResult(BaseModel):
    test_id: str
    title: str
    status: Literal["passed", "failed", "blocked", "skipped"]
    bucket: AutopilotTestBucket = "functional"
    readiness: Optional[Literal["executable", "discovery_required", "approval_required"]] = None
    dependency: Optional[str] = None
    duration_seconds: float = 0
    error: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)
    journey: Optional[str] = None
    page_label: Optional[str] = None
    page_url: Optional[str] = None


class AutopilotSuiteResult(BaseModel):
    job_id: str
    status: Literal["passed", "failed", "partial", "blocked"]
    target_kind: AutopilotTargetKind = "android"
    target_url: Optional[str] = None
    provider: AutopilotProvider
    started_at: str
    finished_at: str
    duration_seconds: float
    device_name: str
    selected_count: int = 0
    executed_count: int = 0
    deferred_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    promoted_count: int = 0
    bucket_counts: Dict[str, int] = Field(default_factory=dict)
    error: Optional[str] = None
    tests: List[AutopilotSuiteTestResult] = Field(default_factory=list)
    continuation_token: Optional[str] = None
    remaining_count: int = Field(default=0, ge=0)


# ``AutopilotApplicationMap`` is declared before the discovery models so it
# can be referenced by the analysis/job contracts above.  Resolve the forward
# references once all of the concrete discovery models are available.
AutopilotApplicationMap.model_rebuild()


