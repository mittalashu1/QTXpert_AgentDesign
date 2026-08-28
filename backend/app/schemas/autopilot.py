"""Schemas for the Android-first QTXpert Autopilot prototype."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


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


class AutopilotAnalysis(BaseModel):
    job_id: str
    filename: str
    platform: Literal["android"] = "android"
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
    recommendation: Literal["GO", "GO_WITH_CONDITIONS", "NO_GO"] = "NO_GO"
    rationale: str
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


class AutopilotJobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    package_name: Optional[str] = None
    app_name: Optional[str] = None
    created_at: str


class AutopilotJobStatus(BaseModel):
    job_id: str
    filename: str
    status: Literal["uploaded", "analyzing", "analyzed", "failed"]
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    created_at: str
    updated_at: str
    context: str = ""
    artifact_available: bool = True
    error: Optional[str] = None
    analysis: Optional[AutopilotAnalysis] = None


class AutopilotProviderStatus(BaseModel):
    browserstack_configured: bool = False
    custom_appium_available: bool = True
    recommended_provider: Literal["browserstack", "appium"] = "appium"


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
    locator_strategy: Optional[Literal["accessibility_id", "id", "xpath"]] = None
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
    tests: List[QTXTestIR] = Field(default_factory=list)


class AutopilotExecutionRequest(BaseModel):
    provider: Literal["browserstack", "appium"] = "browserstack"
    appium_url: Optional[str] = None
    device_name: str = "Google Pixel 8"
    platform_version: Optional[str] = "14.0"
    appium_app: Optional[str] = Field(
        default=None,
        description="Optional app reference for a custom remote Appium provider. BrowserStack uploads the APK automatically.",
    )
    no_reset: bool = False
    auto_grant_permissions: bool = True


class AutopilotExecutionResult(BaseModel):
    execution_id: Optional[UUID] = None
    job_id: str
    status: Literal["passed", "failed", "blocked"]
    provider: Literal["browserstack", "appium"]
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
    context: Optional[str] = Field(default=None, max_length=8000)
    profile_id: str = Field(default="uae_fintech", max_length=80)


class AutopilotDiscoveryRequest(AutopilotExecutionRequest):
    """Bounded safe runtime exploration configuration."""

    max_screens: int = Field(default=12, ge=1, le=40)
    max_actions: int = Field(default=10, ge=0, le=50)
    observe_only: bool = False


class DiscoveryLocator(BaseModel):
    strategy: Literal["accessibility_id", "id", "xpath"]
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
    risk: Literal["safe", "review", "blocked"] = "review"
    risk_reason: Optional[str] = None
    locators: List[DiscoveryLocator] = Field(default_factory=list)


class DiscoveredScreen(BaseModel):
    screen_id: str
    fingerprint: str
    package_name: Optional[str] = None
    activity_name: Optional[str] = None
    screenshot_path: Optional[str] = None
    page_source_path: Optional[str] = None
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
    provider: Literal["browserstack", "appium"]
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
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class AutopilotSuiteRequest(AutopilotExecutionRequest):
    """Execute only IR cases that QTXpert has proven safe and deterministic."""

    test_ids: List[str] = Field(default_factory=list, max_length=20)
    max_tests: int = Field(default=8, ge=1, le=20)


class AutopilotSuiteTestResult(BaseModel):
    test_id: str
    title: str
    status: Literal["passed", "failed", "blocked", "skipped"]
    duration_seconds: float = 0
    error: Optional[str] = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


class AutopilotSuiteResult(BaseModel):
    job_id: str
    status: Literal["passed", "failed", "partial", "blocked"]
    provider: Literal["browserstack", "appium"]
    started_at: str
    finished_at: str
    duration_seconds: float
    device_name: str
    selected_count: int = 0
    executed_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    promoted_count: int = 0
    error: Optional[str] = None
    tests: List[AutopilotSuiteTestResult] = Field(default_factory=list)

