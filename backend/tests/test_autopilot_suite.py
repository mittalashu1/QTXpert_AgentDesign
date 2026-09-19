from pathlib import Path
import base64

import pytest

from app.config import Settings
from app.services.appium_compat import ProviderLifecycleUnavailable
from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
    QTXIRStep,
    QTXTestIR,
)
from app.services.autopilot_suite import AutopilotSuiteService


class _Element:
    def __init__(self):
        self.clicked = False
        self.cleared = False
        self.values = []
        self.text_value = ""

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

    def get_attribute(self, name):
        return self.text_value if name in {"text", "value"} else None


class _Driver:
    def __init__(self):
        self.current_package = "com.qtx.demo"
        self.current_activity = ".MainActivity"
        self.page_source = '<hierarchy><node package="com.qtx.demo" text="Help" /></hierarchy>'
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


class _FlakyLookupDriver(_Driver):
    def __init__(self):
        super().__init__()
        self.lookup_attempts = 0

    def find_element(self, by, value):
        self.lookup_attempts += 1
        if self.lookup_attempts < 3:
            raise RuntimeError("hierarchy is still settling")
        return super().find_element(by, value)


class _ResettableDriver(_Driver):
    def __init__(self):
        super().__init__()
        self.page_source = '<hierarchy package="com.qtx.demo"><node text="Help" /></hierarchy>'
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1


class _ColdRelaunchDriver(_ResettableDriver):
    def __init__(self):
        super().__init__()
        self.terminate_calls = []
        self.activate_calls = []

    def terminate_app(self, package):
        self.terminate_calls.append(package)

    def activate_app(self, package):
        self.activate_calls.append(package)
        super().activate_app(package)


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


def test_suite_interpreter_retries_a_settling_hierarchy(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _FlakyLookupDriver()
    test = _test_ir([
        QTXIRStep(action="tap", description="Open Help", target="Help", locator_strategy="id", locator_value="com.qtx:id/help", locator_confidence=0.97),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert evidence["package"] == "com.qtx.demo"
    assert driver.lookup_attempts == 3
    assert driver.element.clicked is True


def test_suite_interpreter_tries_only_observed_locator_fallbacks(tmp_path, monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())

    class FallbackDriver(_Driver):
        def find_element(self, by, value):
            self.locators.append((by, value))
            if value == "missing-resource-id":
                raise RuntimeError("NoSuchElementException")
            return self.element

    driver = FallbackDriver()
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Open Login",
            target="Login",
            locator_strategy="id",
            locator_value="missing-resource-id",
            locator_confidence=0.97,
            locator_fallbacks=[
                DiscoveryLocator(strategy="accessibility_id", value="Login", confidence=0.96),
            ],
        ),
    ])

    service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert driver.element.clicked is True
    assert [value for _, value in driver.locators] == ["missing-resource-id"] * 8 + ["Login"]


def test_suite_interpreter_blocks_when_tap_leaves_uploaded_app(tmp_path, monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())

    class LeavingElement(_Element):
        def __init__(self, driver):
            super().__init__()
            self.driver = driver

        def click(self):
            super().click()
            self.driver.page_source = (
                '<hierarchy><node package="com.google.android.apps.nexuslauncher" '
                'text="Search apps, web and more" /></hierarchy>'
            )

    class LeavingDriver(_Driver):
        def __init__(self):
            super().__init__()
            self.element = LeavingElement(self)

    driver = LeavingDriver()
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Open Login",
            target="Login",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/login",
            locator_confidence=0.97,
        ),
    ])

    with pytest.raises(RuntimeError, match="left the uploaded app"):
        service._execute_test(driver, test, tmp_path, "com.qtx.demo")


def test_suite_reset_to_application_prefers_provider_reset():
    driver = _ResettableDriver()

    AutopilotSuiteService._reset_to_application(driver, "com.qtx.demo")

    assert driver.reset_calls == 1


def test_suite_reset_to_application_cold_relaunches_after_provider_reset():
    driver = _ColdRelaunchDriver()

    AutopilotSuiteService._reset_to_application(driver, "com.qtx.demo")

    assert driver.reset_calls == 1
    assert driver.terminate_calls == ["com.qtx.demo"]
    assert driver.activate_calls == ["com.qtx.demo"]


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


def test_suite_interpreter_redacts_native_hierarchy_values(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    driver.page_source = (
        '<hierarchy><node class="android.widget.EditText" text="qa@example.test" '
        'value="qa@example.test" password="not-a-secret" /></hierarchy>'
    )
    test = _test_ir([QTXIRStep(action="capture_evidence", description="Capture evidence")])

    service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    xml = next(path for path in tmp_path.iterdir() if path.suffix == ".xml").read_text(encoding="utf-8")
    assert "qa@example.test" not in xml
    assert "not-a-secret" not in xml


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



def _observed_screen(screen_id, controls):
    return DiscoveredScreen(
        screen_id=screen_id,
        fingerprint=f"fingerprint-{screen_id}",
        package_name="com.qtx.demo",
        activity_name=".MainActivity",
        page_label=screen_id,
        controls=controls,
    )


def _navigation_discovery():
    entry = DiscoveredControl(
        control_id="start-entry",
        semantic_label="Get started",
        class_name="android.widget.Button",
        text="Get started",
        resource_id="com.qtx.demo:id/get_started",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/get_started", confidence=0.98)],
    )
    user_id = DiscoveredControl(
        control_id="user-id",
        semantic_label="User ID",
        class_name="android.widget.EditText",
        text="",
        resource_id="com.qtx.demo:id/user_id",
        input_capable=True,
        input_kind="credential",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/user_id", confidence=0.98)],
    )
    password = DiscoveredControl(
        control_id="password",
        semantic_label="Password",
        class_name="android.widget.EditText",
        resource_id="com.qtx.demo:id/password",
        input_capable=True,
        input_kind="credential",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/password", confidence=0.98)],
    )
    submit = DiscoveredControl(
        control_id="login-submit",
        semantic_label="Login",
        class_name="android.widget.Button",
        text="Login",
        resource_id="com.qtx.demo:id/login",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/login", confidence=0.98)],
    )
    root = _observed_screen("screen-root", [entry])
    auth = _observed_screen("screen-auth", [user_id, password, submit])
    return AutopilotDiscoveryResult(
        job_id="test-job",
        status="partial",
        provider="browserstack",
        started_at="2026-09-19T00:00:00Z",
        finished_at="2026-09-19T00:00:01Z",
        duration_seconds=1,
        device_name="test device",
        stop_reason="Authentication screen observed.",
        screens=[root, auth],
        transitions=[
            DiscoveredTransition(
                from_screen_id=root.screen_id,
                to_screen_id=auth.screen_id,
                control_id=entry.control_id,
                control_label=entry.semantic_label,
                action="tap",
            )
        ],
    )


class _RouteDriver(_Driver):
    def __init__(self):
        super().__init__()
        self.root_source = (
            '<hierarchy><node package="com.qtx.demo" class="android.widget.Button" '
            'resource-id="com.qtx.demo:id/get_started" text="Get started" clickable="true" /></hierarchy>'
        )
        self.auth_source = (
            '<hierarchy><node package="com.qtx.demo" class="android.widget.EditText" '
            'resource-id="com.qtx.demo:id/user_id" hint="User ID" />'
            '<node package="com.qtx.demo" class="android.widget.EditText" '
            'resource-id="com.qtx.demo:id/password" hint="Password" />'
            '<node package="com.qtx.demo" class="android.widget.Button" '
            'resource-id="com.qtx.demo:id/login" text="Login" clickable="true" /></hierarchy>'
        )
        self.page_source = self.root_source
        self.navigation_clicks = 0
        self.auth_submit_clicks = 0
        self.back_calls = 0
        self.credential_values = {}

    def find_element(self, by, value):
        self.locators.append((by, value))
        if value == "com.qtx.demo:id/get_started" and self.page_source == self.root_source:
            driver = self

            class EntryElement(_Element):
                def click(inner_self):
                    super(EntryElement, inner_self).click()
                    driver.navigation_clicks += 1
                    driver.page_source = driver.auth_source

            return EntryElement()
        if value == "com.qtx.demo:id/user_id" and self.page_source == self.auth_source:
            element = _Element()
            element.text_value = self.credential_values.get(value, "")
            return element
        if value == "com.qtx.demo:id/password" and self.page_source == self.auth_source:
            element = _Element()
            element.text_value = self.credential_values.get(value, "")
            return element
        if value == "com.qtx.demo:id/login" and self.page_source == self.auth_source:
            driver = self

            class SubmitElement(_Element):
                def click(inner_self):
                    super(SubmitElement, inner_self).click()
                    driver.auth_submit_clicks += 1

            return SubmitElement()
        raise RuntimeError("NoSuchElementException")

    def back(self):
        self.back_calls += 1
        if self.page_source != self.auth_source:
            raise RuntimeError("No safe back route")
        self.page_source = self.root_source


def test_suite_replays_only_observed_safe_route_to_case_screen(tmp_path):
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    driver = _RouteDriver()
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify the User ID field on the observed sign-in screen",
            target="User ID",
            screen_id="screen-auth",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/user_id",
            locator_confidence=0.98,
        )
    ])

    navigation = service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert navigation == [{
        "from_screen": "screen-root",
        "to_screen": "screen-auth",
        "control": "Get started",
    }]
    assert driver.navigation_clicks == 1
    assert driver.auth_submit_clicks == 0
    assert driver.page_source == driver.auth_source


def test_suite_retraces_one_observed_safe_edge_from_empty_sign_in_form():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    discovery.screens[0].page_label = "Authentication"
    discovery.screens[1].page_label = "Authentication"
    driver = _RouteDriver()
    driver.page_source = driver.auth_source
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify Get started on the observed public entry screen",
            target="Get started",
            screen_id="screen-root",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/get_started",
            locator_confidence=0.98,
        )
    ])

    navigation = service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert navigation == [{
        "from_screen": "screen-auth",
        "to_screen": "screen-root",
        "control": "Back to observed public screen (webdriver_back)",
    }]
    assert driver.back_calls == 1
    assert driver.auth_submit_clicks == 0
    assert driver.page_source == driver.root_source


def test_suite_will_not_backtrack_from_a_populated_credential_form():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    driver = _RouteDriver()
    driver.page_source = driver.auth_source
    driver.credential_values["com.qtx.demo:id/user_id"] = "qa@example.test"
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify Get started on the observed public entry screen",
            target="Get started",
            screen_id="screen-root",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/get_started",
            locator_confidence=0.98,
        )
    ])

    with pytest.raises(ProviderLifecycleUnavailable, match="No safe, observed navigation path"):
        service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert driver.back_calls == 0
    assert driver.auth_submit_clicks == 0


def test_missing_route_diagnostic_distinguishes_screens_with_same_label():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery().model_copy(update={"transitions": []})
    discovery.screens[0].page_label = "Authentication"
    discovery.screens[1].page_label = "Authentication"
    driver = _RouteDriver()
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify User ID",
            target="User ID",
            screen_id="screen-auth",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/user_id",
            locator_confidence=0.98,
        )
    ])

    with pytest.raises(ProviderLifecycleUnavailable) as exc_info:
        service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert "Authentication [screen-root]" in str(exc_info.value)
    assert "Authentication [screen-auth]" in str(exc_info.value)


def test_suite_does_not_repeat_sign_in_after_discovery_returns_to_same_screen():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery().model_copy(
        update={"stop_reason": "Sign-in returned to the same screen; credentials may be invalid."}
    )
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Tap Login",
            target="Login",
            screen_id="screen-auth",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/login",
            locator_confidence=0.98,
        )
    ])

    assert service._would_repeat_failed_auth_submission(test, discovery) is True


def test_suite_safe_route_will_not_submit_authentication_controls():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    auth = discovery.screens[1]
    landing = _observed_screen("screen-home", [
        DiscoveredControl(
            control_id="home",
            semantic_label="Home",
            class_name="android.widget.Button",
            text="Home",
            resource_id="com.qtx.demo:id/home",
            clickable=True,
            enabled=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/home", confidence=0.98)],
        )
    ])
    discovery = discovery.model_copy(
        update={
            "screens": [*discovery.screens, landing],
            "transitions": [
                *discovery.transitions,
                DiscoveredTransition(
                    from_screen_id=auth.screen_id,
                    to_screen_id=landing.screen_id,
                    control_id="login-submit",
                    control_label="Login",
                    action="tap",
                ),
            ],
        }
    )

    assert service._safe_discovery_path(discovery, auth.screen_id, landing.screen_id) is None

