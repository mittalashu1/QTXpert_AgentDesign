"""Evidence-backed findings and the business answers used on a follow-up run."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable

from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotBusinessAnswer,
    AutopilotBusinessFinding,
    AutopilotDiscoveryResult,
    AutopilotReportEvidenceAsset,
    AutopilotSuiteResult,
    QTXIRStep,
    QTXTestIR,
)
from app.services.autopilot_instructions import matches_module, route_path


def _finding_id(kind: str, key: str) -> str:
    return f"{kind}-{hashlib.sha256(key.encode()).hexdigest()[:20]}"


def build_business_findings(
    analysis: AutopilotAnalysis,
    discovery: AutopilotDiscoveryResult | None,
    suite: AutopilotSuiteResult | None,
    answers: list[AutopilotBusinessAnswer],
    redact: Callable[[str], str],
    evidence_assets: Iterable[AutopilotReportEvidenceAsset] = (),
) -> list[AutopilotBusinessFinding]:
    findings: dict[str, AutopilotBusinessFinding] = {}
    answered = {answer.finding_id: answer for answer in answers}
    cases_by_observation: dict[tuple[str, str], list[str]] = {}

    def add(kind: str, key: str, title: str, detail: str, question: str, *, case=None, assets=()) -> None:
        identifier = _finding_id(kind, key)
        answer = answered.get(identifier)
        if case and answer and answer.case_title and answer.case_title != case.title:
            answer = None
        findings[identifier] = AutopilotBusinessFinding(
            id=identifier, title=redact(title)[:200], detail=redact(detail)[:1200], question=question,
            case_id=case.test_id if case else None, case_title=redact(case.title) if case else None,
            evidence_asset_ids=[asset for asset in assets if asset], answer=answer,
        )

    if suite:
        for case in suite.tests:
            if case.status not in {"failed", "blocked"} or not (case.error or case.dependency):
                continue
            evidence = [asset.asset_id for asset in evidence_assets if asset.test_id == case.test_id]
            add(
                "case", case.test_id, case.title, case.error or case.dependency or "",
                "What should the app do at this step?", case=case, assets=evidence,
            )
            if case.page_label and case.error:
                key = (case.page_label, case.error)
                cases_by_observation.setdefault(key, []).append(_finding_id("case", case.test_id))
    if discovery:
        for screen in discovery.screens:
            for issue in screen.observed_issues:
                label = screen.page_label or screen.title or screen.screen_id
                related_cases = cases_by_observation.get((label, issue), [])
                assets = [asset for asset in (screen.screenshot_asset_id, screen.page_source_asset_id) if asset]
                if related_cases:
                    for case_id in related_cases:
                        finding = findings[case_id]
                        finding.evidence_asset_ids = list(dict.fromkeys([*finding.evidence_asset_ids, *assets]))
                    continue
                add("screen", f"{label}|{issue}", label, issue, "What should the app show here?",
                    assets=assets)
        for prompt in discovery.runtime_prompts:
            if prompt.kind != "app_confirmation":
                continue
            pending = [choice.label for choice in prompt.choices if choice.outcome_status != "observed"]
            if pending:
                add("prompt", prompt.prompt_id, prompt.title or "App confirmation",
                    "The outcome still needs verification for " + ", ".join(pending) + ".",
                    "What should happen for these choices?", assets=(prompt.screenshot_asset_id,))
        for module in analysis.scope_modules:
            observed = any(
                screen.in_requested_scope and (
                    len(analysis.scope_modules) == 1
                    or matches_module([module], screen.page_label, screen.title, screen.journey, route_path(screen.url))
                )
                for screen in discovery.screens
            )
            if not observed:
                add("module", module.casefold(), f"{module} needs a reachable entry",
                    "The first pass did not verify this module on the app.",
                    "Which visible control opens this module?")
    for answer in answers:
        if answer.finding_id not in findings:
            findings[answer.finding_id] = AutopilotBusinessFinding(
                id=answer.finding_id, title=answer.title,
                detail="Business answer saved from an earlier run.",
                question="What should the app do here?",
                case_id=answer.case_id, case_title=answer.case_title, answer=answer,
            )
    return list(findings.values())


def business_context(answers: Iterable[AutopilotBusinessAnswer]) -> str:
    lines = [f"{answer.case_title or answer.title}: {answer.expected_behavior}" for answer in answers]
    return "\n".join(lines)[:2400]


def apply_business_answer(test: QTXTestIR, answers: Iterable[AutopilotBusinessAnswer]) -> QTXTestIR:
    answer = next((item for item in answers if (
        item.case_title == test.title if item.case_title else item.case_id == test.test_id
    )), None)
    if answer is None:
        return test
    steps = list(test.steps)
    if test.readiness == "executable" and steps and answer.visible_text:
        steps.append(QTXIRStep(
            action="assert_business_text", description="Verify the business-confirmed visible text.",
            assertion=answer.visible_text,
        ))
    return test.model_copy(update={
        "assertions": list(dict.fromkeys([*test.assertions, answer.expected_behavior])),
        "steps": steps,
    })
