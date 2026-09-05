"""Schemas for the unified QTXpert Autopilot target and evidence contract."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


AutopilotTestBucket = Literal[
    "installation",
    "page_level",
    "functional",
    "uat",
    "ui",
    "accessibility",
    "integration",
    "performance",
    "security",
    "compatibility",
    "resilience",
    "permissions",
    "regression",
]
AutopilotTargetKind = Literal["android", "ios", "web"]
AutopilotProvider = Literal["browserstack", "appium", "playwright"]


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


class AutopilotTest(BaseModel):
    id: str
    suite: str
    title: str
    priority: Literal["critical", "high", "medium", "low"] = "medium"
    objective: str
    steps: List[str] = Field(default_factory=list)
    expected: List[str] = Field(default_factory=list)
    autonomous: bool = True
    destructive: bool = False
    source: Literal["deterministic", "ai"] = "deterministic"
    # A bucket describes the kind of coverage, independently from whether the
    # case is executable now. This keeps the generated plan complete while
    # allowing the runner/report to remain evidence-led.
    bucket: AutopilotTestBucket = "functional"
    requires_auth: bool = False
    requires_test_data: bool = False
    dependency: Optional[str] = None
    evidence_required: List[str] = Field(default_factory=list)


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


class AutopilotContextResponse(BaseModel):
    context: str
    source: Literal["default", "ai", "fallback"]
    profile_id: str = "uae_fintech"
    warning: Optional[str] = None


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
    approved_test_ids: List[str] = Field(default_factory=list, max_length=100)
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
    # Optional safe-discovery preferences used when the server chains resume
    # directly into discovery. They contain no credentials or field values.
    discovery_provider: Optional[AutopilotProvider] = None
    discovery_device_name: Optional[str] = Field(default=None, max_length=160)
    discovery_platform_version: Optional[str] = Field(default=None, max_length=80)
    discovery_appium_url: Optional[str] = Field(default=None, max_length=2048)
    discovery_appium_app: Optional[str] = Field(default=None, max_length=2048)


class QTXIRStep(BaseModel):
    action: Literal[
        "launch_app",
        "background_app",
        "restore_app",
        "capture_evidence",
        "inspect_ui",
        "static_assertion",
        "permission_flow",
        "network_condition",
        "intent",
        "tap",
        "assert_visible",
    ]
    description: str
    target: Optional[str] = None
    value: Optional[str] = None
    safe_for_autopilot: bool = True
    screen_id: Optional[str] = None
    locator_strategy: Optional[Literal["accessibility_id", "id", "xpath", "css"]] = None
    locator_value: Optional[str] = None
    locator_confidence: Optional[float] = Field(default=None, ge=0, le=1)


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
    dependency: Optional[str] = None
    promoted_by_discovery: bool = False
    readiness_reason: Optional[str] = None
    steps: List[QTXIRStep] = Field(default_factory=list)
    assertions: List[str] = Field(default_factory=list)
    appium_python: str = ""


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

    max_screens: int = Field(default=12, ge=1, le=40)
    max_actions: int = Field(default=10, ge=0, le=50)
    observe_only: bool = False


class DiscoveryLocator(BaseModel):
    strategy: Literal["accessibility_id", "id", "xpath", "css"]
    value: str
    confidence: float = Field(ge=0, le=1)


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
    input_capable: bool = False
    input_kind: Optional[str] = None
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
    screenshot_path: Optional[str] = None
    page_source_path: Optional[str] = None
    screenshot_asset_id: Optional[UUID] = None
    page_source_asset_id: Optional[UUID] = None
    controls: List[DiscoveredControl] = Field(default_factory=list)


class DiscoveredTransition(BaseModel):
    from_screen_id: str
    to_screen_id: str
    control_id: str
    control_label: str
    action: Literal["tap", "back"] = "tap"
    duplicate_state: bool = False


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
    screens: List[DiscoveredScreen] = Field(default_factory=list)
    transitions: List[DiscoveredTransition] = Field(default_factory=list)
    # Field-specific, non-secret setup references inferred from the live UI.
    # These are informational until the generic credential/data checkpoint is
    # satisfied; values are never captured from the device.
    input_requests: List[AutopilotInputRequest] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class AutopilotSuiteRequest(AutopilotExecutionRequest):
    """Execute safe IR cases and report deferred cases with their dependencies."""

    test_ids: List[str] = Field(default_factory=list, max_length=20)
    buckets: List[AutopilotTestBucket] = Field(default_factory=list, max_length=20)
    max_tests: int = Field(default=8, ge=1, le=20)
    include_deferred: bool = True


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

