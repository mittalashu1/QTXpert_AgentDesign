from pathlib import Path
import base64

import pytest

from app.config import Settings
from app.schemas.autopilot import QTXIRStep, QTXTestIR
from app.services.autopilot_suite import AutopilotSuiteService


class _Element:
    def __init__(self):
        self.clicked = False
        self.cleared = False
        self.values = []

    def is_enabled(self):
        return True

    def is_displayed(self):
        return True

    def click(self):
        self.clicked = True

    def clear(self):
        self.cleared = True
        self.values.clear()

    def send_keys(self, value):
        self.values.append(value)


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


class _RecordingDriver(_Driver):
    def __init__(self):
        super().__init__()
        self.recording_calls = []
        self.stopped = False

    def start_recording_screen(self, **kwargs):
        self.recording_calls.append(kwargs)

    def stop_recording_screen(self):
        self.stopped = True
        return base64.b64encode(b"bounded-video").decode("ascii")


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


def test_suite_interpreter_fills_input_and_suppresses_sensitive_evidence(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    test = _test_ir([
        QTXIRStep(
            action="fill",
            description="Enter password",
            target="Password",
            input_key="runtime_password",
            locator_strategy="id",
            locator_value="com.qtx:id/password",
            locator_confidence=0.97,
        ),
        QTXIRStep(action="capture_evidence", description="Capture evidence"),
    ])

    evidence = service._execute_test(
        driver,
        test,
        tmp_path,
        "com.qtx.demo",
        input_values={"runtime_password": "do-not-log"},
        sensitive_input_keys={"runtime_password"},
    )

    assert driver.element.cleared is True
    assert driver.element.values == ["do-not-log"]
    assert evidence["sensitive_input_evidence_suppressed"] is True
    assert not any(path.suffix in {".png", ".xml"} for path in tmp_path.iterdir())
    assert "do-not-log" not in str(evidence)


def test_functional_video_recording_is_bounded_and_optional(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _RecordingDriver()
    test = _test_ir([QTXIRStep(action="inspect_ui", description="Inspect the current screen")])

    assert service._is_video_case(test) is True
    started, status = service._start_video_recording(driver)
    assert started is True
    assert status == "recording"
    assert driver.recording_calls[0]["time_limit"] == Settings().AUTOPILOT_VIDEO_MAX_SECONDS * 1000

    path, status = service._stop_video_recording(driver, tmp_path / "journey.mp4", suppress=False)
    assert path == tmp_path / "journey.mp4"
    assert status == "captured"
    assert path.read_bytes() == b"bounded-video"
    assert driver.stopped is True


def test_sensitive_functional_video_is_discarded(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _RecordingDriver()
    path, status = service._stop_video_recording(driver, tmp_path / "journey.mp4", suppress=True)

    assert path is None
    assert status == "suppressed_sensitive_input"
    assert not (tmp_path / "journey.mp4").exists()
