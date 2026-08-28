"""Evidence-led executive reporting for Autopilot.

The report deliberately distinguishes static APK evidence, runtime evidence and
user-supplied context. A missing measurement is never converted into a passing
claim, which keeps the release recommendation safe for regulated applications.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotApplicationOverview,
    AutopilotDiscoveryResult,
    AutopilotExecutionRecord,
    AutopilotReportCheck,
    AutopilotReportMetrics,
    AutopilotReportRisk,
    AutopilotSuiteResult,
    AutopilotTestAuditReport,
)


def _contains(context: str, *terms: str) -> bool:
    value = context.lower()
    return any(term.lower() in value for term in terms)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _metrics(
    analysis: AutopilotAnalysis,
    suite: Optional[AutopilotSuiteResult],
    executions: list[AutopilotExecutionRecord],
) -> AutopilotReportMetrics:
    designed = len(analysis.tests)
    executed: Optional[int] = None
    passed = failed = blocked = skipped = 0
    environments: list[str] = []

    if suite is not None:
        statuses = [test.status for test in suite.tests]
        executed = suite.executed_count or sum(status != "skipped" for status in statuses)
        passed = suite.passed_count or statuses.count("passed")
        failed = suite.failed_count or statuses.count("failed")
        blocked = statuses.count("blocked")
        skipped = suite.skipped_count or statuses.count("skipped")
        environments.append(f"{suite.provider} · {suite.device_name}")
    elif executions:
        executed = len(executions)
        passed = sum(item.status == "passed" for item in executions)
        failed = sum(item.status == "failed" for item in executions)
        blocked = sum(item.status == "blocked" for item in executions)
        environments.extend(f"{item.provider} · {item.device_name}" for item in executions)

    pass_rate = round((passed / executed) * 100, 1) if executed else None
    evidence_state = (
        "Runtime suite evidence is available."
        if suite is not None and executed
        else "The suite completed without an executed case; release evidence is incomplete."
        if suite is not None
        else "Smoke execution evidence is available."
        if executions
        else "Runtime execution has not been recorded; release evidence is incomplete."
    )
    defect_count = failed if executed is not None else None
    return AutopilotReportMetrics(
        designed_test_cases=designed,
        executed_test_cases=executed,
        passed_count=passed,
        failed_count=failed,
        blocked_count=blocked,
        skipped_count=skipped,
        pass_rate=pass_rate,
        defect_count=defect_count,
        environment=_unique(environments),
        evidence_state=evidence_state,
    )


def _application_overview(analysis: AutopilotAnalysis, context: str) -> AutopilotApplicationOverview:
    regulators = [name for name in ("CBUAE", "SCA") if _contains(context, name)]
    features: list[str] = []
    feature_terms = (
        ("UAE PASS authentication", ("uae pass", "uaepass")),
        ("Digital KYC onboarding", ("digital kyc", "kyc", "onboarding")),
        ("Automated risk profiling", ("risk profiling", "suitability")),
        ("Managed portfolios (Saver, Flex and Growth)", ("saver", "flex", "growth", "portfolio")),
        ("Investnation Credit Card", ("credit card", "credit limit")),
    )
    for label, terms in feature_terms:
        if _contains(context, *terms):
            features.append(label)
    return AutopilotApplicationOverview(
        name=analysis.app_name or "Android application",
        publisher="Finance House" if _contains(context, "finance house") else "Not specified",
        platform="Android",
        package_name=analysis.package_name or "Not identified",
        version=analysis.version_name or analysis.version_code or "Not identified",
        target_market="UAE residents and investors" if _contains(context, "uae") else "Not specified",
        regulatory_bodies=regulators or ["Not specified"],
        core_features=features or ["Business capabilities not described in the supplied context"],
    )


def _functional_checks(analysis: AutopilotAnalysis, context: str, has_runtime: bool) -> list[AutopilotReportCheck]:
    checks: list[AutopilotReportCheck] = []
    areas = (
        ("onboarding", "Onboarding, UAE PASS and digital KYC", ("uae pass", "uaepass", "kyc", "onboarding")),
        ("portfolio", "Portfolio engine and risk profiling", ("portfolio", "risk profiling", "saver", "flex", "growth")),
        ("credit_card", "Investnation Credit Card integration", ("credit card", "credit limit")),
    )
    for key, title, terms in areas:
        described = _contains(context, *terms)
        status = "pending" if described and not has_runtime else "warning" if described else "not_assessed"
        summary = (
            "The supplied business context identifies this as a release-critical journey; runtime/oracle evidence is still required."
            if described and not has_runtime
            else "The journey is in scope, but the latest runtime evidence did not prove it end to end."
            if described
            else "This journey is not described in the supplied context and cannot be inferred reliably from an APK alone."
        )
        checks.append(
            AutopilotReportCheck(
                key=key,
                title=title,
                status=status,
                summary=summary,
                evidence=["Business context supplied by the user"] if described else ["No supporting business context"],
                recommendation="Provide non-production credentials, test data and backend/oracle assertions before release sign-off." if described else "Confirm whether this capability is in scope.",
            )
        )
    return checks


def _nonfunctional_checks(analysis: AutopilotAnalysis, discovery: Optional[AutopilotDiscoveryResult], has_runtime: bool) -> list[AutopilotReportCheck]:
    security_status = "fail" if analysis.debuggable is True else "pending"
    security_summary = (
        "The APK is marked debuggable; this is a release blocker unless an approved exception exists."
        if analysis.debuggable is True
        else "Manifest permissions and debug posture were inventoried; dynamic penetration and encryption verification are not proven by APK analysis."
    )
    return [
        AutopilotReportCheck(
            key="performance",
            title="Performance and peak concurrency",
            status="pending",
            summary="APK analysis and a mobile smoke run do not measure concurrency, gateway latency or sustained performance.",
            evidence=["No load-test result is attached to this Autopilot job"],
            recommendation="Run an approved load profile and capture p95/p99 latency, error rate and payment-gateway timings.",
        ),
        AutopilotReportCheck(
            key="mobile_footprint",
            title="Mobile footprint and device compatibility",
            status="pending" if not discovery else "warning",
            summary="Static package metadata is available; memory, battery, startup and iOS/cross-device coverage require runtime measurements.",
            evidence=[f"Android manifest inventory: {len(analysis.permissions)} permissions, {len(analysis.activities)} activities"]
            + ([f"Runtime discovery captured {discovery.screen_count} screen(s)"] if discovery else []),
            recommendation="Execute the release matrix on supported iOS/Android real devices and capture resource telemetry.",
        ),
        AutopilotReportCheck(
            key="security",
            title="Security guardrails and package posture",
            status=security_status,
            summary=security_summary,
            evidence=["Static APK manifest inspection"] + (["Debuggable flag is true"] if analysis.debuggable is True else []),
            recommendation="Run approved dynamic security testing and verify TLS, key storage, logging redaction and least-privilege permissions.",
        ),
    ]


def _compliance_checks(context: str) -> list[AutopilotReportCheck]:
    in_scope = _contains(context, "cbuae", "sca", "regulatory", "data residency")
    status = "pending" if in_scope else "not_assessed"
    evidence = ["Regulatory scope is named in the supplied context"] if in_scope else ["No regulatory scope supplied"]
    return [
        AutopilotReportCheck(
            key="regulatory_logging",
            title="CBUAE/SCA audit logging and traceability",
            status=status,
            summary="The APK cannot prove immutable audit logs, retention, clock synchronization, privileged-access review or regulator-ready traceability.",
            evidence=evidence,
            recommendation="Attach backend audit-log samples, retention policy, access reviews and evidence of tamper protection.",
        ),
        AutopilotReportCheck(
            key="data_residency",
            title="Data residency and cross-border processing",
            status=status,
            summary="Data residency, processing locations, subprocessors and transfer controls require infrastructure and legal evidence outside the APK.",
            evidence=evidence,
            recommendation="Document UAE residency requirements, hosting regions, cross-border transfer controls and deletion/retention behavior.",
        ),
    ]


def build_test_audit_report(
    analysis: AutopilotAnalysis,
    context: str,
    *,
    discovery: Optional[AutopilotDiscoveryResult] = None,
    suite: Optional[AutopilotSuiteResult] = None,
    executions: Optional[list[AutopilotExecutionRecord]] = None,
) -> AutopilotTestAuditReport:
    executions = executions or []
    metrics = _metrics(analysis, suite, executions)
    has_runtime = bool(metrics.executed_test_cases)
    functional = _functional_checks(analysis, context, has_runtime)
    nonfunctional = _nonfunctional_checks(analysis, discovery, has_runtime)
    compliance = _compliance_checks(context)

    risks: list[AutopilotReportRisk] = []
    if analysis.debuggable is True:
        risks.append(
            AutopilotReportRisk(
                risk_id="R-AUTO-001",
                title="Debuggable release artifact",
                severity="critical",
                likelihood="high",
                impact="critical",
                evidence="APK manifest reports android:debuggable=true.",
                mitigation="Produce a signed release artifact with debuggable disabled or record an approved exception.",
            )
        )
    if metrics.executed_test_cases is None:
        risks.append(
            AutopilotReportRisk(
                risk_id="R-AUTO-002",
                title="Runtime release evidence is incomplete",
                severity="high",
                likelihood="high",
                impact="high",
                status="pending_validation",
                evidence="No smoke or safe-suite execution is recorded for this job.",
                mitigation="Run the safe smoke and approved functional suite on a real-device target, then attach evidence.",
            )
        )
    if metrics.failed_count:
        risks.append(
            AutopilotReportRisk(
                risk_id="R-AUTO-003",
                title="Runtime failures require triage",
                severity="critical" if metrics.failed_count > 0 else "high",
                likelihood="high",
                impact="high",
                evidence=f"{metrics.failed_count} executed test(s) reported failed.",
                mitigation="Block release until failures are triaged, fixed or formally accepted by the release authority.",
            )
        )
    if metrics.blocked_count:
        risks.append(
            AutopilotReportRisk(
                risk_id="R-AUTO-004",
                title="Tests blocked by environment or guardrails",
                severity="high",
                likelihood="medium",
                impact="high",
                status="pending_validation",
                evidence=f"{metrics.blocked_count} executed test(s) were blocked.",
                mitigation="Restore the test target or provide approved test data; do not count blocked cases as passes.",
            )
        )
    if _contains(context, "cbuae", "sca", "data residency"):
        risks.append(
            AutopilotReportRisk(
                risk_id="R-AUTO-005",
                title="Regulatory evidence is not attached",
                severity="high",
                likelihood="medium",
                impact="critical",
                status="pending_validation",
                evidence="CBUAE/SCA scope is supplied, but audit-log and residency evidence are outside APK analysis.",
                mitigation="Complete the compliance evidence pack and obtain Compliance/Legal sign-off before production release.",
            )
        )

    if metrics.failed_count or metrics.blocked_count or analysis.debuggable is True or not has_runtime:
        recommendation = "NO_GO"
        rationale = "Do not release: one or more release-blocking findings exist or runtime evidence is incomplete."
    elif any(check.status in {"pending", "fail"} for check in compliance):
        recommendation = "GO_WITH_CONDITIONS"
        rationale = "Runtime evidence is positive, but regulatory and non-functional evidence must be completed and approved."
    else:
        recommendation = "GO_WITH_CONDITIONS"
        rationale = "The available evidence supports a conditional release; retain the listed guardrails and monitoring actions."

    findings = [metrics.evidence_state]
    if analysis.debuggable is True:
        findings.append("Critical: the uploaded build is debuggable.")
    if metrics.failed_count:
        findings.append(f"{metrics.failed_count} failed execution result(s) require triage.")
    if not has_runtime:
        findings.append("No runtime pass rate or defect count is claimed until execution is recorded.")
    if discovery:
        findings.append(f"Runtime discovery observed {discovery.screen_count} screen(s) and {discovery.control_count} control(s).")

    recommendations = [
        "Run the bounded safe smoke and autonomous safe suite on an approved real-device target.",
        "Supply non-production credentials, representative data and explicit approval boundaries for authenticated or financial journeys.",
        "Attach backend/API, performance, security and compliance evidence before the release decision is changed to GO.",
    ]
    evidence = [
        f"Static APK analysis: SHA-256 {analysis.sha256}",
        f"Manifest inventory: {len(analysis.permissions)} permission(s), {len(analysis.activities)} activity(ies), {len(analysis.services)} service(s)",
    ]
    if has_runtime:
        evidence.append(metrics.evidence_state)
    else:
        evidence.append("Runtime evidence: not available for this report.")

    return AutopilotTestAuditReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        recommendation=recommendation,
        rationale=rationale,
        executive_findings=_unique(findings),
        application_overview=_application_overview(analysis, context),
        metrics=metrics,
        functional_testing=functional,
        non_functional_testing=nonfunctional,
        compliance_verification=compliance,
        risk_matrix=risks,
        recommendations=recommendations,
        evidence=evidence,
    )

