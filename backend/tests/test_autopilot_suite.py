from pathlib import Path

import pytest

from app.config import Settings
from app.schemas.autopilot import QTXIRStep, QTXTestIR
from app.services.autopilot_suite import AutopilotSuiteService


class _Element:
    def __init__(self):
        self.clicked = False

    def is_enabled(self):
        return True

    def is_displayed(self):
        return True

    def click(self):
        self.clicked = True


class _Driver:
    def __init__(self):
        self.current_package = "com.qtx.demo"
        self.current_activity = ".MainActivity"
        self.page_source = '<hierarchy><node text="Help" /></hierarchy>'
        self.element = _Element()
        self.locators = []

    def find_element(self, by, value):
        self.locators.append((by, value))
        return self.element

    def get_screenshot_as_file(self, path):
        Path(path).write_bytes(b"png")
        return True

    def background_app(self, seconds):
        return None

    def activate_app(self, package):
        self.current_package = package


def _test_ir(actions):
    return QTXTestIR(
        test_id="QT-AI-100",
        title="Safe navigation",
        suite="Navigation",
        priority="medium",
        readiness="executable",
        source="ai",
        promoted_by_discovery=True,
        steps=actions,
    )


def test_suite_runner_supports_only_explicit_ir_allowlist():
    service = AutopilotSuiteService(Settings(), prototype=object())
    safe = _test_ir([
        QTXIRStep(action="tap", description="Open Help", target="Help", locator_strategy="id", locator_value="com.qtx:id/help", locator_confidence=0.97),
        QTXIRStep(action="assert_visible", description="Verify Help", target="Help", locator_strategy="id", locator_value="com.qtx:id/help", locator_confidence=0.97),
    ])
    unsupported = _test_ir([QTXIRStep(action="network_condition", description="Disable network")])

    assert service._supported(safe) is True
    assert service._supported(unsupported) is False


def test_suite_interpreter_executes_resolved_tap_assert_and_evidence(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    test = _test_ir([
        QTXIRStep(action="tap", description="Open Help", target="Help", locator_strategy="id", locator_value="com.qtx:id/help", locator_confidence=0.97),
        QTXIRStep(action="assert_visible", description="Verify Help", target="Help", locator_strategy="id", locator_value="com.qtx:id/help", locator_confidence=0.97),
        QTXIRStep(action="capture_evidence", description="Capture evidence"),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert driver.element.clicked is True
    assert len(driver.locators) == 2
    assert evidence["package"] == "com.qtx.demo"
    assert any(path.suffix == ".png" for path in tmp_path.iterdir())
    assert any(path.suffix == ".xml" for path in tmp_path.iterdir())


def test_suite_interpreter_rejects_non_allowlisted_ir_action(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    test = _test_ir([QTXIRStep(action="intent", description="Do an arbitrary business action")])

    with pytest.raises(RuntimeError, match="not permitted"):
        service._execute_test(driver, test, tmp_path, "com.qtx.demo")
