"""Compile Autopilot test designs into QTX Test IR and Appium Python previews.

QTX Test IR is intentionally tool-independent at the semantic layer. The prototype
also emits Appium Python for cases that are safe and fully specified from runtime
state alone. Tests that depend on undiscovered screen semantics remain explicitly
marked discovery_required instead of pretending brittle code is executable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from textwrap import dedent

from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotAutomationBundle,
    AutopilotTest,
    QTXIRStep,
    QTXTestIR,
)


class AutopilotIRCompiler:
    """Translate QTXpert's mobile test intent into an automation-neutral IR."""

    EXECUTABLE_IDS = {
        "QT-AUTO-SMOKE-001",
        "QT-AUTO-SMOKE-002",
        "QT-AUTO-UX-001",
    }

    def compile_bundle(self, analysis: AutopilotAnalysis) -> AutopilotAutomationBundle:
        compiled = [self.compile_test(test, analysis) for test in analysis.tests]
        return AutopilotAutomationBundle(
            job_id=analysis.job_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            executable_count=sum(test.readiness == "executable" for test in compiled),
            discovery_required_count=sum(test.readiness == "discovery_required" for test in compiled),
            approval_required_count=sum(test.readiness == "approval_required" for test in compiled),
            tests=compiled,
        )

    def compile_test(self, test: AutopilotTest, analysis: AutopilotAnalysis) -> QTXTestIR:
        if test.destructive:
            readiness = "approval_required"
        elif test.id in self.EXECUTABLE_IDS:
            readiness = "executable"
        else:
            readiness = "discovery_required"

        steps = self._ir_steps(test)
        assertions = list(test.expected)
        script = self._appium_script(test, analysis, readiness)
        return QTXTestIR(
            test_id=test.id,
            title=test.title,
            suite=test.suite,
            priority=test.priority,
            readiness=readiness,
            source=test.source,
            steps=steps,
            assertions=assertions,
            appium_python=script,
        )

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
        if test.id == "QT-AUTO-SEC-001" or test.id == "QT-AUTO-SEC-DEBUG":
            return [
                QTXIRStep(action="static_assertion", description=step)
                for step in test.steps
            ]
        if test.id == "QT-AUTO-NET-001":
            return [
                QTXIRStep(action="network_condition", description=step, target="connectivity")
                for step in test.steps
            ]
        if test.id.startswith("QT-AUTO-PERM-"):
            return [
                QTXIRStep(action="permission_flow", description=step, target=test.title.split(" permission", 1)[0].lower())
                for step in test.steps
            ]

        return [
            QTXIRStep(
                action="intent",
                description=step,
                safe_for_autopilot=not test.destructive,
            )
            for step in test.steps
        ]

    def _appium_script(
        self,
        test: AutopilotTest,
        analysis: AutopilotAnalysis,
        readiness: str,
    ) -> str:
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

        reason = (
            "Explicit customer approval is required before compiling this business action."
            if readiness == "approval_required"
            else "Runtime screen/element discovery is required before deterministic Appium locators can be emitted."
        )
        semantic_steps = "\n".join(f"    # {index}. {step}" for index, step in enumerate(test.steps, start=1))
        return dedent(
            f'''\
            def {function_name}(driver, evidence_dir):
                """QTX {test.id}: {test.title}."""
                import pytest

            {semantic_steps or '    # No procedural steps supplied.'}
                pytest.skip({reason!r})
            '''
        ).strip()

    @staticmethod
    def _function_name(test_id: str) -> str:
        safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in test_id)
        safe = "_".join(part for part in safe.split("_") if part)
        return f"test_{safe}"
