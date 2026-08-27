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
    AutopilotTest,
    DiscoveredControl,
    DiscoveredScreen,
    QTXIRStep,
    QTXTestIR,
)


class AutopilotIRCompiler:
    """Translate QTXpert mobile test intent into automation-neutral IR."""

    EXECUTABLE_IDS = {
        "QT-AUTO-SMOKE-001",
        "QT-AUTO-SMOKE-002",
        "QT-AUTO-UX-001",
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
    ) -> AutopilotAutomationBundle:
        compiled = [self.compile_test(test, analysis, discovery) for test in analysis.tests]
        return AutopilotAutomationBundle(
            job_id=analysis.job_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            discovery_used=bool(discovery and discovery.screens),
            promoted_count=sum(test.promoted_by_discovery for test in compiled),
            executable_count=sum(test.readiness == "executable" for test in compiled),
            discovery_required_count=sum(test.readiness == "discovery_required" for test in compiled),
            approval_required_count=sum(test.readiness == "approval_required" for test in compiled),
            tests=compiled,
        )

    def compile_test(
        self,
        test: AutopilotTest,
        analysis: AutopilotAnalysis,
        discovery: Optional[AutopilotDiscoveryResult] = None,
    ) -> QTXTestIR:
        promoted = False
        readiness_reason: Optional[str] = None
        resolved_steps: Optional[list[QTXIRStep]] = None

        if test.destructive:
            readiness = "approval_required"
            readiness_reason = "The test is marked destructive and requires explicit customer approval."
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
            promoted_by_discovery=promoted,
            readiness_reason=readiness_reason,
            steps=ir_steps,
            assertions=list(test.expected),
        )
        generated.appium_python = self._appium_script(test, analysis, generated)
        return generated

    def _ir_steps(self, test: AutopilotTest) -> list[QTXIRStep]:
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

        if test.id == "QT-AUTO-SMOKE-001":
            return dedent(
                f'''\
                def {function_name}(driver, evidence_dir):
                    """QTX {test.id}: {test.title}."""
                    from pathlib import Path
                    import time

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    time.sleep(3)
                    package = driver.current_package
                    activity = getattr(driver, "current_activity", None)
                    assert package, "Application did not reach a foreground package"
                    driver.get_screenshot_as_file(str(evidence_dir / "{test.id.lower()}.png"))
                    page_source = driver.page_source or ""
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

                    evidence_dir = Path(evidence_dir)
                    evidence_dir.mkdir(parents=True, exist_ok=True)
                    package = driver.current_package or {package_hint!r}
                    assert package, "Unable to determine application package"
                    driver.background_app(2)
                    time.sleep(1)
                    driver.activate_app(package)
                    time.sleep(2)
                    assert driver.current_package == package, "Application did not recover to foreground"
                    driver.get_screenshot_as_file(str(evidence_dir / "{test.id.lower()}.png"))
                    return {{"package": driver.current_package, "activity": getattr(driver, "current_activity", None)}}
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
            lines.append("    return {'package': driver.current_package, 'activity': getattr(driver, 'current_activity', None)}")
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
