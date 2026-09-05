"""Compile Autopilot designs into QTX Test IR and safe Appium Python.

QTX Test IR 0.2 can consume Runtime Discovery. A test is promoted from
``discovery_required`` to ``executable`` only when each interactive step can be
resolved against the current discovered screen with a deterministic locator and
QTXpert's safe-action policy. Ambiguous, input-dependent and blocked actions stay
non-executable instead of emitting brittle or unsafe automation.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from textwrap import dedent
from typing import Optional

from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAutomationBundle,
    AutopilotDiscoveryResult,
    AutopilotInputRequest,
    AutopilotSetupProfile,
    AutopilotTest,
    DiscoveredControl,
    DiscoveredScreen,
    QTXIRStep,
    QTXTestIR,
)


_INPUT_REQUEST_METADATA: dict[str, tuple[str, str, str, bool]] = {
    "credential reference": (
        "credential_reference",
        "Approved credential-set reference",
        "credential",
        True,
    ),
    "test account role": (
        "account_role",
        "Test account role",
        "credential",
        False,
    ),
    "safe authentication approval": (
        "safe_authentication_approved",
        "Safe authentication approval",
        "approval",
        False,
    ),
    "synthetic test-data reference": (
        "test_data_reference",
        "Synthetic test-data reference",
        "test_data",
        False,
    ),
    "reset/cleanup reference": (
        "reset_hook_reference",
        "Reset/cleanup reference",
        "test_data",
        False,
    ),
    "signed-off acceptance criteria reference": (
        "acceptance_criteria_reference",
        "Signed-off acceptance criteria reference",
        "acceptance",
        False,
    ),
    "API/oracle reference": (
        "api_oracle_reference",
        "API/oracle reference",
        "integration",
        False,
    ),
}

# The checkpoint is a customer-facing workflow, not an implementation error
# list. Keep the stable compiler field names above, but attach plain-language
# prompts and safe examples so a user understands what belongs in each field.
_INPUT_REQUEST_GUIDANCE: dict[str, dict[str, str | bool | None]] = {
    "credential reference": {
        "question": "Which non-production account should Autopilot use to sign in?",
        "placeholder": "Enter the UAT user ID/email and password below",
        "format_hint": "Use a test account only. The two values are encrypted together and never sent to the AI model or written to logs.",
        "credential_bundle": True,
        "input_hint": "username",
    },
    "test account role": {
        "question": "What role should this account have during the journey?",
        "placeholder": "e.g., Retail investor / UAT customer",
        "format_hint": "Use the business role configured in the non-production environment.",
    },
    "safe authentication approval": {
        "question": "May Autopilot sign in to the approved non-production environment?",
        "format_hint": "This approval only permits safe, non-transactional authentication; payments, OTP and destructive actions remain gated.",
    },
    "synthetic test-data reference": {
        "question": "Which synthetic fixture should the dependent cases use?",
        "placeholder": "e.g., qtxpert://data/investnation-uat",
        "format_hint": "Provide a fixture/vault reference, not raw production data.",
    },
    "reset/cleanup reference": {
        "question": "How should the test data be reset after the run?",
        "placeholder": "e.g., qtxpert://hooks/investnation-reset",
        "format_hint": "Use a reversible reset hook or fixture reference.",
    },
    "signed-off acceptance criteria reference": {
        "question": "Where are the signed-off acceptance criteria for this UAT case?",
        "placeholder": "e.g., qtxpert://docs/investnation-uat-criteria",
        "format_hint": "Link to an approved repository document or requirements record.",
    },
    "API/oracle reference": {
        "question": "Which API, ledger or business oracle should validate the outcome?",
        "placeholder": "e.g., qtxpert://oracles/investnation-ledger",
        "format_hint": "Use a non-production endpoint/fixture reference; do not paste tokens.",
    },
}


def build_input_requests(
    analysis: AutopilotAnalysis,
    setup: Optional[AutopilotSetupProfile] = None,
) -> list[AutopilotInputRequest]:
    """Group deferred dependencies into a user-facing checkpoint.

    The compiler remains the single source of truth for readiness rules.  The
    UI gets one request per missing reference, including the exact test cases
    that depend on it, instead of a long opaque error string.
    """

    compiler = AutopilotIRCompiler()
    dependents: dict[str, list[str]] = {}
    for test in analysis.tests:
        for field in compiler._missing_setup(test, setup):
            dependents.setdefault(field, []).append(test.id)
    requests: list[AutopilotInputRequest] = []
    for field in sorted(dependents):
        metadata = _INPUT_REQUEST_METADATA.get(field)
        if metadata is None:
            key, label, category, sensitive = field.replace(" ", "_"), field.title(), "environment", False
        else:
            key, label, category, sensitive = metadata
        reason = {
            "credential": "A non-production credential-set reference is needed for an approved authenticated journey. Store the secret in the configured vault; provide only its reference here.",
            "approval": "Explicit approval is required before Autopilot can enter an authenticated non-transactional flow.",
            "test_data": "Seeded synthetic data and a reset/cleanup hook keep repeated runs isolated and reversible.",
            "acceptance": "UAT assertions need signed-off acceptance criteria so business outcomes are not inferred.",
            "integration": "An API contract, oracle or observable backend reference is needed to validate integration outcomes.",
            "environment": "The target environment must be identified before this case can be executed.",
        }[category]
        guidance = _INPUT_REQUEST_GUIDANCE.get(field, {})
        requests.append(
            AutopilotInputRequest(
                key=key,
                label=label,
                category=category,
                reason=reason,
                required_for=sorted(set(dependents[field])),
                sensitive=sensitive,
                status="pending",
                reference_present=False,
                question=str(guidance.get("question") or "What should Autopilot use for this setup item?"),
                placeholder=str(guidance.get("placeholder")) if guidance.get("placeholder") else None,
                format_hint=str(guidance.get("format_hint")) if guidance.get("format_hint") else None,
                credential_bundle=bool(guidance.get("credential_bundle")),
                input_hint=(guidance.get("input_hint") if guidance.get("input_hint") else None),  # type: ignore[arg-type]
            )
        )
    return requests


class AutopilotIRCompiler:
    """Translate QTXpert mobile test intent into automation-neutral IR."""

    EXECUTABLE_IDS = {
        "QT-AUTO-SMOKE-001",
        "QT-AUTO-SMOKE-002",
        "QT-AUTO-UX-001",
        "QT-AUTO-UI-001",
    }
    WEB_EXECUTABLE_IDS = {
        "QT-WEB-SMOKE-001",
        "QT-WEB-PAGE-001",
        "QT-WEB-A11Y-001",
        "QT-WEB-SEC-001",
    }
    _TAP_RE = re.compile(r"^(?:tap|click|open|navigate\s+to|go\s+to|select|choose|press)\s+(.+)$", re.I)
    _ASSERT_RE = re.compile(r"^(?:verify|check|ensure|assert|observe|validate)\s+(.+)$", re.I)
    _INPUT_RE = re.compile(r"^(?:enter|type|input|fill|provide)\b", re.I)
    _STOP_WORDS = {
        "the", "a", "an", "button", "link", "icon", "option", "menu", "screen", "page",
        "field", "control", "tab", "to", "on", "is", "are", "be", "displayed", "visible",
        "shown", "appears", "should", "successfully", "application", "app",
    }

    def compile_bundle(
        self,
        analysis: AutopilotAnalysis,
        discovery: Optional[AutopilotDiscoveryResult] = None,
        setup: Optional[AutopilotSetupProfile] = None,
    ) -> AutopilotAutomationBundle:
        compiled = [self.compile_test(test, analysis, discovery, setup) for test in analysis.tests]
        bucket_counts: dict[str, int] = {}
        for test in compiled:
            bucket_counts[test.bucket] = bucket_counts.get(test.bucket, 0) + 1
        setup_missing = sorted({
            field
            for test in analysis.tests
            for field in self._missing_setup(test, setup)
        })
        return AutopilotAutomationBundle(
            job_id=analysis.job_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            framework="QTX Test IR + Playwright Python" if analysis.target_kind == "web" else "QTX Test IR + Appium Python",
            discovery_used=bool(discovery and discovery.screens),
            promoted_count=sum(test.promoted_by_discovery for test in compiled),
            executable_count=sum(test.readiness == "executable" for test in compiled),
            discovery_required_count=sum(test.readiness == "discovery_required" for test in compiled),
            approval_required_count=sum(test.readiness == "approval_required" for test in compiled),
            bucket_counts=bucket_counts,
            setup_provided_count=len(setup.provided_fields) if setup else 0,
            setup_missing_fields=setup_missing,
            tests=compiled,
        )

    def compile_test(
        self,
        test: AutopilotTest,
        analysis: AutopilotAnalysis,
        discovery: Optional[AutopilotDiscoveryResult] = None,
        setup: Optional[AutopilotSetupProfile] = None,
    ) -> QTXTestIR:
        promoted = False
        readiness_reason: Optional[str] = None
        resolved_steps: Optional[list[QTXIRStep]] = None

        missing_setup = self._missing_setup(test, setup)
        if test.destructive:
            readiness = "approval_required"
            if setup and test.id in setup.approved_test_ids:
                readiness_reason = (
                    "Approval is recorded, but financial/destructive actions remain restricted to a supervised run."
                )
            else:
                readiness_reason = "The test is marked destructive and requires explicit customer approval."
        elif missing_setup:
            readiness = "discovery_required"
            readiness_reason = "Provide setup: " + "; ".join(missing_setup) + "."
        elif analysis.target_kind == "web" and test.id in self.WEB_EXECUTABLE_IDS:
            readiness = "executable"
            readiness_reason = "Deterministic Playwright public-surface check."
        elif test.id in self.EXECUTABLE_IDS:
            readiness = "executable"
            readiness_reason = "Deterministic platform-level Autopilot check."
        elif discovery and discovery.screens:
            resolved_steps, readiness_reason = self._resolve_semantic_steps(test, discovery)
            if resolved_steps:
                readiness = "executable"
                promoted = True
            else:
                readiness = "discovery_required"
        else:
            readiness = "discovery_required"
            readiness_reason = "Runtime screen/element discovery is required before deterministic locators can be emitted."

        ir_steps = resolved_steps if resolved_steps is not None else self._ir_steps(test)
        generated = QTXTestIR(
            test_id=test.id,
            title=test.title,
            suite=test.suite,
            priority=test.priority,
            readiness=readiness,
            source=test.source,
            bucket=test.bucket,
            requires_auth=test.requires_auth,
            requires_test_data=test.requires_test_data,
            dependency=test.dependency,
            promoted_by_discovery=promoted,
            readiness_reason=readiness_reason,
            steps=ir_steps,
            assertions=list(test.expected),
        )
        generated.appium_python = self._appium_script(test, analysis, generated)
        return generated

    @staticmethod
    def _missing_setup(
        test: AutopilotTest,
        setup: Optional[AutopilotSetupProfile],
    ) -> list[str]:
        def has_value(field: str, category: Optional[str] = None) -> bool:
            if setup is None:
                return False
            if str(getattr(setup, field, "") or "").strip():
                return True
            decisions = getattr(setup, "input_decisions", {}) or {}
            accepted = {"provide", "reuse", "random"}
            if decisions.get(field) in accepted:
                return True
            if category:
                for request in [*(getattr(setup, "input_requests", []) or []), *(getattr(setup, "runtime_input_requests", []) or [])]:
                    if request.category == category and decisions.get(request.key) in accepted:
                        return True
            return False

        missing: list[str] = []
        if test.requires_auth:
            if not has_value("credential_reference", "credential"):
                missing.append("credential reference")
            if not has_value("account_role"):
                missing.append("test account role")
            if not setup or not setup.safe_authentication_approved:
                missing.append("safe authentication approval")
        if test.requires_test_data:
            if not has_value("test_data_reference", "test_data"):
                missing.append("synthetic test-data reference")
            if not has_value("reset_hook_reference"):
                missing.append("reset/cleanup reference")
        if test.bucket == "uat" and not has_value("acceptance_criteria_reference"):
            missing.append("signed-off acceptance criteria reference")
        if test.bucket == "integration" and not has_value("api_oracle_reference"):
            missing.append("API/oracle reference")
        return missing

    def _ir_steps(self, test: AutopilotTest) -> list[QTXIRStep]:
        if test.id.startswith("QT-WEB-"):
            return [
                QTXIRStep(action="inspect_ui", description="Inspect the rendered website DOM and interactive surface."),
                QTXIRStep(action="capture_evidence", description="Capture website screenshot and HTML evidence."),
            ]
        if test.id == "QT-AUTO-SMOKE-001":
            return [
                QTXIRStep(action="launch_app", description="Create an Android automation session and launch the uploaded application."),
                QTXIRStep(action="inspect_ui", description="Confirm the application reaches a readable foreground UI."),
                QTXIRStep(action="capture_evidence", description="Capture screenshot, UI hierarchy, package, activity and orientation."),
            ]
        if test.id == "QT-AUTO-SMOKE-002":
            return [
                QTXIRStep(action="launch_app", description="Start from a stable foreground application state."),
                QTXIRStep(action="background_app", description="Send the application to the background briefly."),
                QTXIRStep(action="restore_app", description="Restore the same package to foreground."),
                QTXIRStep(action="capture_evidence", description="Capture post-recovery state and evidence."),
            ]
        if test.id == "QT-AUTO-UX-001":
            return [
                QTXIRStep(action="inspect_ui", description="Read Android UI hierarchy and enumerate semantic controls."),
                QTXIRStep(action="capture_evidence", description="Record UI hierarchy for accessibility and semantic analysis."),
            ]
        if test.id == "QT-AUTO-UI-001":
            return [
                QTXIRStep(action="inspect_ui", description="Inspect the current page for layout, labels and interaction metadata."),
                QTXIRStep(action="capture_evidence", description="Capture the page screenshot and UI hierarchy for visual review."),
            ]
        if test.id in {"QT-AUTO-SEC-001", "QT-AUTO-SEC-DEBUG"}:
            return [QTXIRStep(action="static_assertion", description=step) for step in test.steps]
        if test.id == "QT-AUTO-NET-001":
            return [QTXIRStep(action="network_condition", description=step, target="connectivity") for step in test.steps]
        if test.id.startswith("QT-AUTO-PERM-"):
            return [
                QTXIRStep(action="permission_flow", description=step, target=test.title.split(" permission", 1)[0].lower())
                for step in test.steps
            ]
        return [QTXIRStep(action="intent", description=step, safe_for_autopilot=not test.destructive) for step in test.steps]

    def _resolve_semantic_steps(
        self,
        test: AutopilotTest,
        discovery: AutopilotDiscoveryResult,
    ) -> tuple[Optional[list[QTXIRStep]], str]:
        if discovery.status not in {"completed", "partial"} or not discovery.screens:
            return None, "Runtime Discovery has no usable screen graph."

        screens = {screen.screen_id: screen for screen in discovery.screens}
        current = discovery.screens[0]
        transitions = {
            (transition.from_screen_id, transition.control_id): transition
            for transition in discovery.transitions
            if transition.action == "tap"
        }
        resolved: list[QTXIRStep] = []
        assertion_count = 0

        for raw_step in test.steps:
            step = re.sub(r"^\s*\d+[.)-]?\s*", "", raw_step.strip())
            if not step:
                continue
            if self._INPUT_RE.match(step):
                return None, f"Input/test-data step still requires controlled data: {raw_step}"
            if re.search(r"\b(?:launch|start)\s+(?:the\s+)?(?:application|app)\b", step, re.I):
                resolved.append(QTXIRStep(action="launch_app", description=raw_step, screen_id=current.screen_id))
                continue

            tap_match = self._TAP_RE.match(step)
            if tap_match:
                control = self._best_control(current, tap_match.group(1), interaction=True)
                if control is None:
                    return None, f"No high-confidence safe control matched step: {raw_step}"
                locator = self._best_locator(control, interaction=True)
                if locator is None:
                    return None, f"No deterministic locator is strong enough for: {control.semantic_label}"
                transition = transitions.get((current.screen_id, control.control_id))
                resolved.append(
                    QTXIRStep(
                        action="tap",
                        description=raw_step,
                        target=control.semantic_label,
                        screen_id=current.screen_id,
                        locator_strategy=locator.strategy,
                        locator_value=locator.value,
                        locator_confidence=locator.confidence,
                    )
                )
                if transition and transition.to_screen_id in screens:
                    current = screens[transition.to_screen_id]
                continue

            assert_match = self._ASSERT_RE.match(step)
            if assert_match:
                control = self._best_control(current, assert_match.group(1), interaction=False)
                if control is None:
                    return None, f"No high-confidence visible control matched assertion: {raw_step}"
                locator = self._best_locator(control, interaction=False)
                if locator is None:
                    return None, f"No deterministic assertion locator is strong enough for: {control.semantic_label}"
                resolved.append(
                    QTXIRStep(
                        action="assert_visible",
                        description=raw_step,
                        target=control.semantic_label,
                        screen_id=current.screen_id,
                        locator_strategy=locator.strategy,
                        locator_value=locator.value,
                        locator_confidence=locator.confidence,
                    )
                )
                assertion_count += 1
                continue

            return None, f"Unsupported semantic step requires further learning: {raw_step}"

        if not resolved:
            return None, "The test has no runtime steps that can be executed safely."

        if assertion_count == 0:
            expected_assert = self._resolve_expected_assertion(test, current)
            if expected_assert:
                resolved.append(expected_assert)
                assertion_count = 1

        if assertion_count == 0:
            return None, "A deterministic post-action assertion could not be resolved on the discovered state."

        resolved.append(QTXIRStep(action="capture_evidence", description="Capture evidence after the resolved semantic journey.", screen_id=current.screen_id))
        return resolved, "All runtime interactions and at least one assertion were resolved from the discovered screen graph with safe deterministic locators."

    def _resolve_expected_assertion(self, test: AutopilotTest, screen: DiscoveredScreen) -> Optional[QTXIRStep]:
        for expected in test.expected:
            control = self._best_control(screen, expected, interaction=False)
            if control is None:
                continue
            locator = self._best_locator(control, interaction=False)
            if locator is None:
                continue
            return QTXIRStep(
                action="assert_visible",
                description=f"Expected: {expected}",
                target=control.semantic_label,
                screen_id=screen.screen_id,
                locator_strategy=locator.strategy,
                locator_value=locator.value,
                locator_confidence=locator.confidence,
            )
        return None

    def _best_control(self, screen: DiscoveredScreen, phrase: str, interaction: bool) -> Optional[DiscoveredControl]:
        candidates: list[tuple[float, DiscoveredControl]] = []
        for control in screen.controls:
            if not control.enabled or not control.locators:
                continue
            if interaction and (not control.clickable or control.risk != "safe"):
                continue
            score = self._semantic_score(phrase, control)
            if score >= (0.78 if interaction else 0.72):
                candidates.append((score, control))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (-item[0], -max(locator.confidence for locator in item[1].locators)))
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
            return None
        return candidates[0][1]

    def _semantic_score(self, phrase: str, control: DiscoveredControl) -> float:
        target = self._normalize_phrase(phrase)
        if not target:
            return 0
        fields = [control.semantic_label, control.text, control.content_description, control.resource_id.rsplit("/", 1)[-1]]
        best = 0.0
        target_tokens = set(target.split())
        for field in fields:
            candidate = self._normalize_phrase(field)
            if not candidate:
                continue
            if target == candidate:
                best = max(best, 1.0)
                continue
            if target in candidate or candidate in target:
                best = max(best, 0.92)
            tokens = set(candidate.split())
            if target_tokens and tokens:
                overlap = len(target_tokens & tokens) / len(target_tokens | tokens)
                best = max(best, overlap)
        return best

    def _normalize_phrase(self, value: str) -> str:
        value = value.lower().replace("_", " ").replace("-", " ")
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        tokens = [token for token in value.split() if token not in self._STOP_WORDS]
        return " ".join(tokens)

    @staticmethod
    def _best_locator(control: DiscoveredControl, interaction: bool):
        minimum = 0.90 if interaction else 0.82
        candidates = [locator for locator in control.locators if locator.confidence >= minimum]
        if not candidates:
            return None
        candidates.sort(key=lambda locator: -locator.confidence)
        return candidates[0]

    def _appium_script(self, test: AutopilotTest, analysis: AutopilotAnalysis, generated: QTXTestIR) -> str:
        function_name = self._function_name(test.id)
        package_hint = analysis.package_name or ""

        if analysis.target_kind == "web":
            target_url = analysis.target_url or ""
            return dedent(
                f'''\
                def {function_name}(browser, evidence_dir):
                    """QTX {test.id}: {test.title}."""
                    from pathlib import Path

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    page = browser.new_page()
                    response = page.goto({target_url!r}, wait_until="domcontentloaded", timeout=45000)
                    assert response is None or response.status < 400, f"Website returned HTTP {{response.status if response else 'unknown'}}"
                    page.screenshot(path=str(evidence_dir / "{test.id.lower()}.png"), full_page=True)
                    (evidence_dir / "{test.id.lower()}.html").write_text(page.content(), encoding="utf-8")
                    return {{"url": page.url, "title": page.title(), "status_code": response.status if response else None}}
                '''
            ).strip()

        if test.id == "QT-AUTO-SMOKE-001":
            return dedent(
                f'''\
                def {function_name}(driver, evidence_dir):
                    """QTX {test.id}: {test.title}."""
                    from pathlib import Path
                    import time
                    from app.services.appium_compat import safe_app_identity, safe_page_source

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    time.sleep(3)
                    page_source = safe_page_source(driver)
                    identity = safe_app_identity(driver, page_source=page_source, package_hint={package_hint!r})
                    package = identity["package"]
                    activity = identity["activity"]
                    assert package, "Application did not reach a foreground package"
                    driver.get_screenshot_as_file(str(evidence_dir / "{test.id.lower()}.png"))
                    (evidence_dir / "{test.id.lower()}.xml").write_text(page_source, encoding="utf-8")
                    assert page_source.strip(), "No readable Android UI hierarchy was returned"
                    return {{"package": package, "activity": activity, "page_source_chars": len(page_source)}}
                '''
            ).strip()

        if test.id == "QT-AUTO-SMOKE-002":
            return dedent(
                f'''\
                def {function_name}(driver, evidence_dir):
                    """QTX {test.id}: {test.title}."""
                    from pathlib import Path
                    import time
                    from app.services.appium_compat import safe_app_identity, safe_background_application, safe_page_source

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    identity = safe_app_identity(driver, page_source=safe_page_source(driver), package_hint={package_hint!r})
                    package = identity["package"]
                    assert package, "Unable to determine application package"
                    lifecycle_mechanism = safe_background_application(driver, 2, package=package)
                    time.sleep(1)
                    driver.activate_app(package)
                    time.sleep(2)
                    restored = safe_app_identity(driver, page_source=safe_page_source(driver))
                    assert restored["package"] == package, "Application did not recover to foreground"
                    driver.get_screenshot_as_file(str(evidence_dir / "{test.id.lower()}.png"))
                    return {{"package": restored["package"], "activity": restored["activity"], "lifecycle_mechanism": lifecycle_mechanism}}
                '''
            ).strip()

        if test.id == "QT-AUTO-UX-001":
            return dedent(
                f'''\
                def {function_name}(driver, evidence_dir):
                    """QTX {test.id}: semantic UI baseline."""
                    from pathlib import Path
                    import re

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    xml = driver.page_source or ""
                    assert xml.strip(), "No UI hierarchy available for semantic inspection"
                    clickable = len(re.findall(r'clickable="true"', xml, flags=re.IGNORECASE))
                    labelled = len(re.findall(r'(?:text|content-desc)="[^"]+"', xml, flags=re.IGNORECASE))
                    (evidence_dir / "{test.id.lower()}.xml").write_text(xml, encoding="utf-8")
                    return {{"clickable_controls": clickable, "labelled_nodes": labelled}}
                '''
            ).strip()

        if generated.readiness == "executable" and generated.promoted_by_discovery:
            lines = [
                f"def {function_name}(driver, evidence_dir):",
                f'    """QTX {test.id}: discovery-resolved semantic journey."""',
                "    from pathlib import Path",
                "    import time",
                "    from appium.webdriver.common.appiumby import AppiumBy",
                "    from app.services.appium_compat import safe_app_identity, safe_page_source",
                "",
                "    evidence_dir = Path(evidence_dir)",
                "    evidence_dir.mkdir(parents=True, exist_ok=True)",
                "    locator_map = {'accessibility_id': AppiumBy.ACCESSIBILITY_ID, 'id': AppiumBy.ID, 'xpath': AppiumBy.XPATH}",
            ]
            for index, step in enumerate(generated.steps, start=1):
                if step.action == "launch_app":
                    lines.extend([f"    # {index}. {step.description}", "    time.sleep(1)"])
                elif step.action in {"tap", "assert_visible"}:
                    lines.extend([
                        f"    # {index}. {step.description}",
                        f"    element = driver.find_element(locator_map[{step.locator_strategy!r}], {step.locator_value!r})",
                    ])
                    if step.action == "tap":
                        lines.extend(["    assert element.is_enabled(), 'Resolved control is disabled'", "    element.click()", "    time.sleep(1)"])
                    else:
                        lines.append("    assert element.is_displayed(), 'Resolved semantic control is not visible'")
                elif step.action == "capture_evidence":
                    lines.extend([
                        f"    # {index}. {step.description}",
                        f"    driver.get_screenshot_as_file(str(evidence_dir / '{test.id.lower()}.png'))",
                        "    xml = driver.page_source or ''",
                        f"    (evidence_dir / '{test.id.lower()}.xml').write_text(xml, encoding='utf-8')",
                    ])
            lines.extend([
                "    identity = safe_app_identity(driver, page_source=safe_page_source(driver))",
                "    return {'package': identity['package'], 'activity': identity['activity']}",
            ])
            return "\n".join(lines)

        reason = (
            "Explicit customer approval is required before compiling this business action."
            if generated.readiness == "approval_required"
            else generated.readiness_reason or "Runtime screen/element discovery is required before deterministic Appium locators can be emitted."
        )
        lines = [
            f"def {function_name}(driver, evidence_dir):",
            f'    """QTX {test.id}: {test.title}."""',
            "    import pytest",
            "",
        ]
        lines.extend(f"    # {index}. {step}" for index, step in enumerate(test.steps, start=1))
        if not test.steps:
            lines.append("    # No procedural steps supplied.")
        lines.append(f"    pytest.skip({reason!r})")
        return "\n".join(lines)

    @staticmethod
    def _function_name(test_id: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in test_id)
        safe = "_".join(part for part in safe.split("_") if part)
        return f"test_{safe}"


