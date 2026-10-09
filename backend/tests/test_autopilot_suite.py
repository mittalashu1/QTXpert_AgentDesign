from pathlib import Path
import base64

import pytest

from app.config import Settings
from app.services.appium_compat import ProviderLifecycleUnavailable, validate_target_surface
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


class _SystemUiForegroundDriver(_Driver):
    def __init__(self, *, launch_target=True):
        super().__init__()
        self.current_package = "com.google.android.gms"
        self.page_source = '<hierarchy><node package="com.google.android.gms" text="Google Play services" /></hierarchy>'
        self.launch_target = launch_target
        self.activate_calls = []

    def activate_app(self, package):
        self.activate_calls.append(package)
        if self.launch_target:
            self.current_package = package
            self.page_source = f'<hierarchy><node package="{package}" text="Sign in" /></hierarchy>'


class _ObservedActivityDriver(_ColdRelaunchDriver):
    def __init__(self):
        super().__init__()
        self.explicit_activity_calls = []

    def start_activity(self, package, activity):
        self.explicit_activity_calls.append((package, activity))
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


def test_suite_uses_native_back_when_observed_back_locator_is_unavailable(tmp_path, monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    native_back_calls = []

    def native_back(_driver, *, target_kind):
        native_back_calls.append(target_kind)
        return "android_mobile_press_key"

    monkeypatch.setattr("app.services.autopilot_suite.safe_navigate_back", native_back)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    original_find = service._find_semantic_element

    def unavailable_back(_driver, step, locator_map):
        if step.target == "Back":
            raise RuntimeError("NoSuchElementException")
        return original_find(_driver, step, locator_map)

    monkeypatch.setattr(service, "_find_semantic_element", unavailable_back)
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Tap Back",
            target="Back",
            locator_strategy="accessibility_id",
            locator_value="Back",
            locator_confidence=0.95,
        ),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert native_back_calls == ["android"]
    assert evidence["actions"][0]["mechanism"] == "android_mobile_press_key"


def test_suite_uses_native_back_when_only_observed_locator_has_back_label(tmp_path, monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    native_back_calls = []

    def native_back(_driver, *, target_kind):
        native_back_calls.append(target_kind)
        return "android_mobile_press_key"

    monkeypatch.setattr("app.services.autopilot_suite.safe_navigate_back", native_back)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    def unavailable_back(_driver, _step, _locator_map):
        raise RuntimeError("NoSuchElementException")

    monkeypatch.setattr(service, "_find_semantic_element", unavailable_back)
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Exercise the observed control",
            target="Authentication",
            locator_strategy="accessibility_id",
            locator_value="Back",
            locator_confidence=0.95,
        ),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert native_back_calls == ["android"]
    assert evidence["actions"][0]["mechanism"] == "android_mobile_press_key"


def test_suite_uses_native_back_when_observed_back_control_stales_before_click(tmp_path, monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    native_back_calls = []

    class StaleBackElement(_Element):
        def click(self):
            raise RuntimeError("StaleElementReferenceException")

    driver = _Driver()
    driver.element = StaleBackElement()

    def native_back(_driver, *, target_kind):
        native_back_calls.append(target_kind)
        return "android_mobile_press_key"

    monkeypatch.setattr("app.services.autopilot_suite.safe_navigate_back", native_back)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Tap Back",
            target="Back",
            locator_strategy="accessibility_id",
            locator_value="Back",
            locator_confidence=0.95,
        ),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert native_back_calls == ["android"]
    assert evidence["actions"][0]["mechanism"] == "android_mobile_press_key"


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


def test_suite_reset_waits_for_delayed_app_foreground_after_lifecycle_restart(monkeypatch):
    now = [0.0]
    package = "com.qtx.demo"

    class _DelayedForegroundDriver(_SystemUiForegroundDriver):
        def __init__(self):
            super().__init__(launch_target=False)
            self.terminate_calls = []

        def terminate_app(self, target_package):
            self.terminate_calls.append(target_package)
            self.current_package = "com.google.android.gms"
            self.page_source = '<hierarchy><node package="com.google.android.gms" text="Google Play services" /></hierarchy>'

    driver = _DelayedForegroundDriver()

    def advance(seconds):
        now[0] += seconds
        if now[0] >= 3.0:
            driver.current_package = package
            driver.page_source = f'<hierarchy><node package="{package}" text="Sign in" /></hierarchy>'

    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", advance)
    monkeypatch.setattr("app.services.autopilot_suite.time.monotonic", lambda: now[0])

    AutopilotSuiteService._reset_to_application(driver, package)

    ready, reason, _ = validate_target_surface(driver, expected_package=package)
    assert ready is True, reason
    assert driver.terminate_calls == [package]
    assert driver.activate_calls == [package, package]
    assert now[0] >= 3.0


def test_suite_reactivates_uploaded_app_when_new_session_starts_in_system_ui(monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _SystemUiForegroundDriver()
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    ready, reason, identity = service._activate_verified_target(
        driver,
        "com.qtx.demo",
        timeout_seconds=0,
    )

    assert ready is True, reason
    assert driver.activate_calls == ["com.qtx.demo"]
    assert identity["package"] == "com.qtx.demo"


def test_suite_keeps_wrong_foreground_blocked_after_activation_retry(monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _SystemUiForegroundDriver(launch_target=False)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    ready, reason, _ = service._activate_verified_target(
        driver,
        "com.qtx.demo",
        timeout_seconds=0,
    )

    assert ready is False
    assert "com.google.android.gms" in reason
    assert "com.qtx.demo" in reason
    assert driver.activate_calls == ["com.qtx.demo"]


def test_suite_retries_package_after_ineffective_activity_start(monkeypatch):
    class _AcknowledgesActivityWithoutForeground(_SystemUiForegroundDriver):
        def __init__(self):
            super().__init__()
            self.activity_calls = []

        def start_activity(self, package, activity):
            self.activity_calls.append((package, activity))
            # Provider acknowledges the command but leaves Google Play services visible.

    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _AcknowledgesActivityWithoutForeground()
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    ready, reason, identity = service._activate_verified_target(
        driver,
        "com.qtx.demo",
        activity_hint="com.qtx.demo.MainActivity",
        timeout_seconds=0,
        poll_interval=0,
    )

    assert ready is True, reason
    assert driver.activity_calls == [("com.qtx.demo", "com.qtx.demo.MainActivity")]
    assert driver.activate_calls == ["com.qtx.demo"]
    assert identity["package"] == "com.qtx.demo"


def test_suite_reset_relaunches_the_observed_activity_without_package_launcher_resolution(monkeypatch):
    driver = _ObservedActivityDriver()
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    AutopilotSuiteService._reset_to_application(
        driver,
        "com.qtx.demo",
        "com.qtx.demo.MainActivity",
    )

    assert driver.explicit_activity_calls == [("com.qtx.demo", "com.qtx.demo.MainActivity")]
    assert driver.reset_calls == 0
    assert driver.activate_calls == []
    assert driver.terminate_calls == ["com.qtx.demo"]


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


def test_suite_waits_briefly_for_sparse_launch_screen_to_settle(monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    discovery.screens[0].controls = [DiscoveredControl(
        control_id="splash",
        semantic_label="Loading",
        class_name="android.widget.TextView",
        enabled=True,
        risk="safe",
    )]
    driver = _RouteDriver()
    observations = [discovery.screens[0], discovery.screens[0], discovery.screens[1]]

    def identify(_driver, _discovery, _package):
        result = observations.pop(0) if observations else discovery.screens[1]
        if result.screen_id == "screen-auth":
            driver.page_source = driver.auth_source
        return result

    monkeypatch.setattr(service, "_identify_discovered_screen", identify)
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

    assert navigation == []
    assert driver.navigation_clicks == 0
    assert driver.page_source == driver.auth_source

def test_suite_relaunches_once_when_sparse_launch_screen_does_not_settle(monkeypatch):
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    discovery.screens[0].controls = [
        DiscoveredControl(
            control_id="splash-root",
            semantic_label="View",
            class_name="android.view.View",
            enabled=True,
            risk="review",
        )
    ]
    driver = _RouteDriver()
    activation_calls = []

    service._claim_transient_launch_settle_attempt = lambda *_args: False

    def reactivate(driver, package, activity, **_kwargs):
        activation_calls.append((package, activity))
        driver.page_source = driver.auth_source

    service._activate_application = reactivate
    service._identify_discovered_screen = lambda _driver, _discovery, _package: (
        discovery.screens[1]
        if driver.page_source == driver.auth_source
        else discovery.screens[0]
    )
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

    navigation = service._prepare_test_screen(
        driver,
        test,
        discovery,
        "com.qtx.demo",
        transient_launch_settle_attempted={"screen-root"},
        transient_launch_recovery_attempted=set(),
    )

    assert navigation == []
    assert activation_calls == [("com.qtx.demo", None)]
    assert driver.page_source == driver.auth_source


def test_suite_selection_prioritizes_allow_prompt_branch_for_startup_crawl():
    from types import SimpleNamespace

    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = SimpleNamespace(
        runtime_prompts=[
            SimpleNamespace(
                prompt_id="permission-prompt",
                choices=[
                    SimpleNamespace(key="allow", decision="allow"),
                    SimpleNamespace(key="deny", decision="deny"),
                ],
            )
        ]
    )

    def candidate(test_id, prompt_choice):
        return SimpleNamespace(
            test_id=test_id,
            readiness="executable",
            runtime_prompt_id="permission-prompt",
            runtime_prompt_choice=prompt_choice,
            steps=[SimpleNamespace(action="prompt_choice")],
        )

    deny_case = candidate("deny", "deny")
    allow_case = candidate("allow", "allow")
    smoke_case = SimpleNamespace(
        test_id="smoke",
        readiness="executable",
        runtime_prompt_id=None,
        runtime_prompt_choice=None,
        steps=[SimpleNamespace(action="inspect_ui")],
    )

    ordered = sorted(
        [deny_case, allow_case, smoke_case],
        key=lambda test: service._selection_priority(test, discovery),
    )

    assert [test.test_id for test in ordered] == ["smoke", "allow", "deny"]


def test_device_farm_prompt_reset_requires_confirmed_uninstall():
    class Driver:
        def __init__(self):
            self.installed = True

        def remove_app(self, _package):
            self.installed = True
            return self

        def is_app_installed(self, _package):
            return self.installed

    class DeviceFarm:
        def __init__(self):
            self.installs = []

        def install_app_in_session(self, *args):
            self.installs.append(args)

    class Session:
        arn = "arn:remote-session"
        app_arn = "arn:uploaded-app"

    device_farm = DeviceFarm()
    with pytest.raises(ProviderLifecycleUnavailable, match="still reports the app installed"):
        AutopilotSuiteService._reset_device_farm_prompt_state(
            Driver(),
            "com.qtx.demo",
            device_farm,
            Session(),
        )
    assert device_farm.installs == []


def test_device_farm_prompt_reset_keeps_appium_session_open_and_verifies_reinstall():
    events = []

    class Driver:
        installed = True

        def remove_app(self, _package):
            events.append("uninstall")
            self.installed = False

        def is_app_installed(self, _package):
            events.append("verify_installed")
            return self.installed

    driver = Driver()

    class DeviceFarm:
        def install_app_in_session(self, *_args):
            events.append("install")
            driver.installed = True

    class Session:
        arn = "arn:remote-session"
        app_arn = "arn:uploaded-app"

    AutopilotSuiteService._reset_device_farm_prompt_state(
        driver,
        "com.qtx.demo",
        DeviceFarm(),
        Session(),
    )

    assert events == ["uninstall", "verify_installed", "install", "verify_installed"]
    assert driver.installed is True


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
        "control": "Back to observed screen (webdriver_back)",
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


def test_missing_route_with_same_label_is_repaired_from_observed_safe_control():
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

    navigation = service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert navigation == [{
        "from_screen": "screen-root",
        "to_screen": "screen-auth",
        "control": "Get started",
    }]
    assert driver.navigation_clicks == 1


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


def test_suite_treats_volatile_duplicate_surface_as_same_replay_page():
    service = AutopilotSuiteService(Settings(), prototype=object())
    first = _observed_screen("screen-001", [
        DiscoveredControl(
            control_id="promo-one",
            semantic_label="100",
            class_name="android.widget.TextView",
            resource_id="com.qtx.demo:id/promo",
            enabled=True,
            locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/promo", confidence=0.99)],
        ),
    ])
    second = first.model_copy(
        update={
            "screen_id": "screen-002",
            "fingerprint": "different-provider-fingerprint",
            "controls": [first.controls[0].model_copy(update={"semantic_label": "11"})],
        }
    )

    assert service._screens_equivalent(first, second) is True







def test_suite_does_not_force_restart_before_first_verified_case(tmp_path, monkeypatch):
    import appium
    from app.schemas.autopilot import AutopilotSuiteRequest

    driver = _ColdRelaunchDriver()
    driver.quit = lambda: None
    monkeypatch.setattr(appium.webdriver, "Remote", lambda *args, **kwargs: driver)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    service = AutopilotSuiteService(Settings(), prototype=Prototype())
    request = AutopilotSuiteRequest(
        target_kind="android",
        provider="devicefarm",
        device_name="Google Pixel 8",
        max_tests=1,
    )
    test = _test_ir([
        QTXIRStep(action="inspect_ui", description="Inspect the verified target screen"),
    ]).model_copy(update={"bucket": "installation"})

    results = service._run_sync(
        "job-123",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        request,
        [test],
        "com.qtx.demo",
        None,
        None,
        1000,
        1000,
        1000,
    )

    assert results[0].status == "passed"
    assert driver.reset_calls == 0
    assert driver.terminate_calls == []


class _GuestReturnDriver(_RouteDriver):
    def back(self):
        self.back_calls += 1
        if self.page_source != self.root_source:
            raise RuntimeError("No safe observed guest-page back route")
        self.page_source = self.auth_source


def _guest_to_auth_discovery():
    discovery = _navigation_discovery()
    discovery.screens[0].page_label = "Guest home"
    discovery.screens[1].page_label = "Authentication"
    discovery.screens[1].controls.append(
        DiscoveredControl(
            control_id="guest-entry",
            semantic_label="Explore as a Guest",
            class_name="android.widget.Button",
            text="Explore as a Guest",
            resource_id="com.qtx.demo:id/explore_guest",
            clickable=True,
            enabled=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="id", value="com.qtx.demo:id/explore_guest", confidence=0.98)],
        )
    )
    discovery.transitions = [
        DiscoveredTransition(
            from_screen_id="screen-auth",
            to_screen_id="screen-root",
            control_id="guest-entry",
            control_label="Explore as a Guest",
            action="tap",
        )
    ]
    return discovery


def test_suite_returns_from_guest_screen_to_observed_empty_authentication_form():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _guest_to_auth_discovery()
    driver = _GuestReturnDriver()
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify the User ID field on the observed authentication screen",
            target="User ID",
            screen_id="screen-auth",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/user_id",
            locator_confidence=0.98,
        )
    ])
    service._repair_live_route = lambda *_args: None

    navigation = service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert navigation == [{
        "from_screen": "screen-root",
        "to_screen": "screen-auth",
        "control": "Back to observed screen (webdriver_back)",
    }]
    assert driver.back_calls == 1
    assert driver.auth_submit_clicks == 0
    assert driver.page_source == driver.auth_source


def test_suite_will_not_use_reverse_guest_route_when_authentication_fields_are_populated():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _guest_to_auth_discovery()
    driver = _GuestReturnDriver()
    driver.credential_values["com.qtx.demo:id/user_id"] = "user@example.test"
    test = _test_ir([
        QTXIRStep(
            action="assert_visible",
            description="Verify the User ID field on the observed authentication screen",
            target="User ID",
            screen_id="screen-auth",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/user_id",
            locator_confidence=0.98,
        )
    ])
    service._repair_live_route = lambda *_args: None

    with pytest.raises(ProviderLifecycleUnavailable, match="credential fields already contain values"):
        service._prepare_test_screen(driver, test, discovery, "com.qtx.demo")

    assert driver.back_calls == 1
    assert driver.auth_submit_clicks == 0


def test_suite_prompt_choice_accepts_a_new_observed_system_prompt(tmp_path):
    class PromptFollowupDriver(_Driver):
        def __init__(self):
            super().__init__()
            self.current_activity = (
                "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"
            )
            self.page_source = (
                '<hierarchy><node package="com.android.permissioncontroller" '
                'class="android.widget.FrameLayout">'
                '<node package="com.android.permissioncontroller" text="Location permission" '
                'class="android.widget.TextView" />'
                '<node package="com.android.permissioncontroller" text="Don\'t allow" '
                'resource-id="com.android.permissioncontroller:id/deny_button" '
                'class="android.widget.Button" clickable="true" enabled="true" />'
                '</node></hierarchy>'
            )

        def find_element(self, by, value):
            self.locators.append((by, value))
            driver = self

            class PromptChoice(_Element):
                def click(inner_self):
                    super(PromptChoice, inner_self).click()
                    driver.current_activity = (
                        "com.google.android.location.settings.LocationSettingsCheckerActivity"
                    )
                    driver.page_source = (
                        '<hierarchy><node package="com.google.android.gms" '
                        'text="Location settings checker activity" '
                        'class="android.widget.FrameLayout">'
                        '<node package="com.google.android.gms" text="No thanks" '
                        'resource-id="com.google.android.gms:id/negative_button" '
                        'class="android.widget.Button" clickable="true" enabled="true" />'
                        '</node></hierarchy>'
                    )

            return PromptChoice()

    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = PromptFollowupDriver()
    test = _test_ir([
        QTXIRStep(
            action="prompt_choice",
            description="Choose Don’t allow on the observed location permission prompt",
            target="runtime_permission",
            value="dont-allow",
            assertion="deny",
            locator_strategy="id",
            locator_value="com.android.permissioncontroller:id/deny_button",
            locator_confidence=0.98,
        ),
        QTXIRStep(action="inspect_ui", description="Inspect the next checkpoint"),
        QTXIRStep(action="capture_evidence", description="Capture the resulting checkpoint"),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert evidence["actions"][0]["resulting_prompt_kind"] == "location_settings"
    assert evidence["actions"][0]["resulting_prompt_id"]
    assert evidence["actions"][0]["mechanism"] == "observed_prompt_choice:deny"
    strict_test = test.model_copy(update={
        "steps": [
            test.steps[0].model_copy(update={"expected_resulting_prompt_id": "unexpected-prompt"}),
            *test.steps[1:],
        ]
    })
    with pytest.raises(AssertionError, match="did not reach its observed follow-up system prompt"):
        service._execute_test(PromptFollowupDriver(), strict_test, tmp_path, "com.qtx.demo")


def test_suite_routes_matching_startup_prompt_case_before_app_cases(tmp_path, monkeypatch):
    import appium
    from app.schemas.autopilot import AutopilotSuiteRequest

    class StartupPromptDriver(_Driver):
        def __init__(self):
            super().__init__()
            self.prompt_active = True
            self.current_activity = (
                "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"
            )
            self.page_source = (
                '<hierarchy><node package="com.android.permissioncontroller" '
                'text="Allow while using the app" />'
                '<node package="com.android.permissioncontroller" text="Don\'t allow" />'
                '</hierarchy>'
            )

    driver = StartupPromptDriver()
    monkeypatch.setattr(appium.webdriver, "Remote", lambda *_args, **_kwargs: driver)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    service = AutopilotSuiteService(Settings(), prototype=Prototype())
    service._activate_verified_target = lambda _driver, package, **_kwargs: (
        True,
        "ready",
        {"package": package},
    )
    service._reset_to_application = lambda *_args, **_kwargs: None
    execution_order = []

    def execute(_driver, test, *_args, **_kwargs):
        execution_order.append(test.test_id)
        if test.test_id == "startup-prompt":
            driver.prompt_active = False
            driver.current_activity = ".MainActivity"
            driver.page_source = (
                '<hierarchy><node package="com.qtx.demo" text="Welcome" /></hierarchy>'
            )
        return {}

    service._execute_test = execute
    smoke_test = _test_ir([
        QTXIRStep(action="launch_app", description="Launch the uploaded app."),
        QTXIRStep(action="inspect_ui", description="Inspect its current screen."),
    ]).model_copy(update={"test_id": "cold-launch"})
    prompt_test = _test_ir([
        QTXIRStep(
            action="prompt_choice",
            description="Choose an observed runtime permission option.",
            target="runtime_permission",
            value="deny",
            locator_strategy="id",
            locator_value="com.android.permissioncontroller:id/deny_button",
            locator_confidence=0.98,
        ),
    ]).model_copy(update={"test_id": "startup-prompt"})

    results = service._run_sync(
        "job-startup-prompt",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        AutopilotSuiteRequest(
            target_kind="android",
            provider="devicefarm",
            device_name="Google Pixel 8",
            max_tests=2,
        ),
        [smoke_test, prompt_test],
        "com.qtx.demo",
        None,
        1000,
        1000,
        1000,
    )

    assert execution_order == ["startup-prompt", "cold-launch"]
    assert [result.test_id for result in results] == ["cold-launch", "startup-prompt"]
    assert all(result.status == "passed" for result in results)


def test_suite_device_farm_reinstalls_app_to_rearm_prompt_cases(tmp_path, monkeypatch):
    import appium
    from app.schemas.autopilot import AutopilotSuiteRequest

    class PromptDriver(_ColdRelaunchDriver):
        def __init__(self):
            super().__init__()
            self.current_package = "com.qtx.demo"
            self.page_source = '<hierarchy><node package="com.qtx.demo" text="Welcome" /></hierarchy>'
            self.prompt_active = True
            self.quit_calls = 0
            self.removed_packages = []
            self.app_installed = True
            self.install_checks = []

        def remove_app(self, package):
            self.removed_packages.append(package)
            self.app_installed = False
            return self

        def is_app_installed(self, package):
            self.install_checks.append(package)
            return self.app_installed

        def execute_script(self, command, arguments):
            raise AssertionError("Device Farm permission replay must not use unsupported mobile extensions")

        def quit(self):
            self.quit_calls += 1

    driver = PromptDriver()
    calls = []

    def remote(url, options, **_kwargs):
        calls.append((url, options.to_capabilities()))
        return driver

    monkeypatch.setattr(appium.webdriver, "Remote", remote)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "app.services.autopilot_suite.known_native_prompt_kind",
        lambda current_driver, _source, _target: "runtime_permission" if current_driver.prompt_active else None,
    )

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    class DeviceFarm:
        def __init__(self):
            self.installs = []

        def install_app_in_session(self, session_arn, app_arn):
            self.installs.append((session_arn, app_arn))
            driver.app_installed = True

    class Session:
        arn = "arn:remote-session"
        app_arn = "arn:uploaded-app"

    device_farm = DeviceFarm()
    service = AutopilotSuiteService(Settings(), prototype=Prototype())
    service._activate_verified_target = lambda current_driver, package, **_kwargs: (
        True,
        "ready",
        {"package": package},
    )
    service._execute_test = lambda *_args, **_kwargs: {}
    request = AutopilotSuiteRequest(
        target_kind="android",
        provider="devicefarm",
        device_name="Google Pixel 8",
        max_tests=2,
    )
    prompt_tests = [
        _test_ir([
            QTXIRStep(
                action="prompt_choice",
                description="Choose an observed permission prompt option",
                target="runtime_permission",
                locator_strategy="id",
                locator_value="com.android.permissioncontroller:id/deny_button",
                locator_confidence=0.98,
            )
        ]).model_copy(update={"test_id": f"prompt-{index}", "bucket": "installation"})
        for index in range(2)
    ]

    results = service._run_sync(
        "job-prompts",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        request,
        prompt_tests,
        "com.qtx.demo",
        None,
        None,
        1000,
        1000,
        1000,
        device_farm_service=device_farm,
        device_farm_session=Session(),
    )

    assert [result.status for result in results] == ["passed", "passed"]
    assert len(calls) == 1
    assert all("appium:fastReset" not in capabilities for _, capabilities in calls)
    assert all("appium:fullReset" not in capabilities for _, capabilities in calls)
    assert driver.quit_calls == 1
    assert driver.removed_packages == ["com.qtx.demo"]
    assert driver.install_checks == ["com.qtx.demo", "com.qtx.demo"]
    assert device_farm.installs == [("arn:remote-session", "arn:uploaded-app")]




def test_suite_short_circuits_screen_cases_after_target_foreground_failure(tmp_path, monkeypatch):
    import appium
    from app.schemas.autopilot import AutopilotSuiteRequest

    driver = _SystemUiForegroundDriver(launch_target=False)
    driver.quit = lambda: None
    monkeypatch.setattr(appium.webdriver, "Remote", lambda *args, **kwargs: driver)
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    recovery_checks = []

    def recovery_verification(*_args, **_kwargs):
        recovery_checks.append(True)
        return False, "Runtime session reached only Android system UI; the uploaded application was not launched.", {}

    monkeypatch.setattr(
        AutopilotSuiteService,
        "_activate_verified_target",
        staticmethod(recovery_verification),
    )

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    service = AutopilotSuiteService(Settings(), prototype=Prototype())
    service._activate_verified_target = lambda _driver, package, **_kwargs: (
        True,
        "ready",
        {"package": package},
    )
    request = AutopilotSuiteRequest(
        target_kind="android",
        provider="devicefarm",
        device_name="Google Pixel 8",
        max_tests=3,
    )
    screen_tests = [
        _test_ir([
            QTXIRStep(
                action="inspect_ui",
                description="Inspect the observed app screen",
                screen_id="screen-root",
            ),
        ]).model_copy(update={"test_id": f"screen-{index}", "bucket": "installation"})
        for index in range(3)
    ]

    results = service._run_sync(
        "job-screen-failure",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        request,
        screen_tests,
        "com.qtx.demo",
        None,
        None,
        1000,
        1000,
        1000,
    )

    assert [result.status for result in results] == ["blocked", "blocked", "blocked"]
    assert recovery_checks == [True]
    assert all(result.error for result in results)


def test_suite_does_not_retry_failed_device_farm_prompt_reset(tmp_path, monkeypatch):
    import appium
    from app.schemas.autopilot import AutopilotSuiteRequest

    class PromptDriver(_ColdRelaunchDriver):
        def __init__(self):
            super().__init__()
            self.prompt_active = False
            self.removed_packages = []
            self.app_installed = True
            self.install_checks = []
            self.quit_calls = 0

        def remove_app(self, package):
            self.removed_packages.append(package)
            self.app_installed = False
            return self

        def is_app_installed(self, package):
            self.install_checks.append(package)
            return self.app_installed

        def quit(self):
            self.quit_calls += 1

    driver = PromptDriver()
    remote_calls = []
    monkeypatch.setattr(
        appium.webdriver,
        "Remote",
        lambda url, options, **_kwargs: remote_calls.append((url, options.to_capabilities())) or driver,
    )
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "app.services.autopilot_suite.known_native_prompt_kind",
        lambda current, _source, _target: "runtime_permission" if current.prompt_active else None,
    )

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    class DeviceFarm:
        def __init__(self):
            self.installs = []

        def install_app_in_session(self, session_arn, app_arn):
            self.installs.append((session_arn, app_arn))
            raise RuntimeError("provider reset unavailable")

    class Session:
        arn = "arn:remote-session"
        app_arn = "arn:uploaded-app"

    device_farm = DeviceFarm()
    service = AutopilotSuiteService(Settings(), prototype=Prototype())
    service._activate_verified_target = lambda current, package, **_kwargs: (
        True,
        "ready",
        {"package": package},
    )
    request = AutopilotSuiteRequest(
        target_kind="android",
        provider="devicefarm",
        device_name="Google Pixel 8",
        max_tests=3,
    )
    prompt_tests = [
        _test_ir([
            QTXIRStep(
                action="prompt_choice",
                description="Replay an observed permission branch",
                target="runtime_permission",
                value="dont-allow",
                locator_strategy="id",
                locator_value="com.android.permissioncontroller:id/deny_button",
                locator_confidence=0.98,
            ),
        ]).model_copy(update={"test_id": f"prompt-failure-{index}", "bucket": "installation"})
        for index in range(3)
    ]

    results = service._run_sync(
        "job-prompt-failure",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        request,
        prompt_tests,
        "com.qtx.demo",
        None,
        None,
        1000,
        1000,
        1000,
        device_farm_service=device_farm,
        device_farm_session=Session(),
    )

    assert [result.status for result in results] == ["blocked", "blocked", "blocked"]
    assert len(remote_calls) == 1
    assert device_farm.installs == [("arn:remote-session", "arn:uploaded-app")]
    assert driver.removed_packages == ["com.qtx.demo"]
    assert driver.install_checks == ["com.qtx.demo"]
    assert driver.quit_calls == 1


def test_identify_discovered_screen_uses_unique_observed_token_for_sparse_hierarchy():
    service = AutopilotSuiteService(Settings(), prototype=object())
    discovery = _navigation_discovery()
    driver = _RouteDriver()
    driver.page_source = (
        '<hierarchy><node package="com.qtx.demo" '
        'content-desc="Get started" /></hierarchy>'
    )

    screen = service._identify_discovered_screen(driver, discovery, "com.qtx.demo")

    assert screen is not None
    assert screen.screen_id == "screen-root"


def test_suite_prompt_choice_uses_observed_locator_fallback(tmp_path):
    class PromptFallbackDriver(_Driver):
        def __init__(self):
            super().__init__()
            self.current_activity = (
                "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"
            )
            self.page_source = (
                '<hierarchy><node package="com.android.permissioncontroller" '
                'class="android.widget.FrameLayout">'
                '<node package="com.android.permissioncontroller" text="Location permission" '
                'class="android.widget.TextView" />'
                '<node package="com.android.permissioncontroller" text="Don\'t allow" '
                'resource-id="com.android.permissioncontroller:id/deny_button" '
                'class="android.widget.Button" clickable="true" enabled="true" />'
                '</node></hierarchy>'
            )
            self.fallback_element = self._choice_element()

        def _choice_element(self):
            driver = self

            class PromptChoice(_Element):
                def click(inner_self):
                    super(PromptChoice, inner_self).click()
                    driver.current_activity = ".MainActivity"
                    driver.current_package = "com.qtx.demo"
                    driver.page_source = (
                        '<hierarchy><node package="com.qtx.demo" text="Home" /></hierarchy>'
                    )

            return PromptChoice()

        def find_element(self, by, value):
            self.locators.append((by, value))
            if value == "missing-primary-locator":
                raise RuntimeError("NoSuchElementException")
            if value == "Don\'t allow":
                return self.fallback_element
            raise RuntimeError("NoSuchElementException")

    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = PromptFallbackDriver()
    test = _test_ir([
        QTXIRStep(
            action="prompt_choice",
            description="Choose Don’t allow using its observed fallback locator",
            target="runtime_permission",
            value="dont-allow",
            assertion="deny",
            locator_strategy="id",
            locator_value="missing-primary-locator",
            locator_confidence=0.98,
            locator_fallbacks=[
                DiscoveryLocator(
                    strategy="accessibility_id",
                    value="Don\'t allow",
                    confidence=0.97,
                ),
            ],
        ),
        QTXIRStep(action="inspect_ui", description="Inspect the resulting app screen"),
        QTXIRStep(action="capture_evidence", description="Capture the resulting app screen"),
    ])

    evidence = service._execute_test(driver, test, tmp_path, "com.qtx.demo")

    assert [value for _, value in driver.locators] == [
        "missing-primary-locator",
        "Don\'t allow",
    ]
    assert driver.fallback_element.clicked is True
    assert evidence["actions"][0]["mechanism"] == "observed_prompt_choice:deny"

def test_suite_confirmation_assertion_passes_only_when_observed_screen_changes(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)

    class ChangingDriver(_Driver):
        def __init__(self):
            super().__init__()
            self.page_source = (
                '<hierarchy><node package="com.qtx.demo" class="android.widget.Button" '
                'text="Proceed" resource-id="com.qtx.demo:id/proceed" clickable="true" /></hierarchy>'
            )

        def find_element(self, by, value):
            self.locators.append((by, value))
            driver = self

            class TransitionElement(_Element):
                def click(inner_self):
                    super(TransitionElement, inner_self).click()
                    driver.page_source = (
                        '<hierarchy><node package="com.qtx.demo" class="android.widget.Button" '
                        'text="Home" resource-id="com.qtx.demo:id/home" clickable="true" /></hierarchy>'
                    )

            return TransitionElement()

    service = AutopilotSuiteService(Settings(), prototype=object())
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Tap Proceed",
            target="Proceed",
            screen_id="confirmation",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/proceed",
            locator_confidence=0.99,
        ),
        QTXIRStep(
            action="assert_screen_changed",
            description="Verify the application leaves or changes the observed confirmation state",
            screen_id="confirmation",
        ),
    ])

    assert service._supported(test)
    evidence = service._execute_test(
        ChangingDriver(), test, tmp_path, "com.qtx.demo", discovery=None,
    )
    assert evidence["actions"][1]["mechanism"] == "observed_screen_changed"


def test_suite_confirmation_assertion_fails_when_screen_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.autopilot_suite.time.sleep", lambda _seconds: None)
    service = AutopilotSuiteService(Settings(), prototype=object())
    driver = _Driver()
    driver.page_source = (
        '<hierarchy><node package="com.qtx.demo" class="android.widget.Button" '
        'text="Proceed" resource-id="com.qtx.demo:id/proceed" clickable="true" /></hierarchy>'
    )
    test = _test_ir([
        QTXIRStep(
            action="tap",
            description="Tap Proceed",
            target="Proceed",
            screen_id="confirmation",
            locator_strategy="id",
            locator_value="com.qtx.demo:id/proceed",
            locator_confidence=0.99,
        ),
        QTXIRStep(
            action="assert_screen_changed",
            description="Verify the application leaves or changes the observed confirmation state",
            screen_id="confirmation",
        ),
    ])

    with pytest.raises(AssertionError, match="did not change the observed application state"):
        service._execute_test(driver, test, tmp_path, "com.qtx.demo", discovery=None)



def test_sparse_launch_recovery_attempts_are_limited_per_test_and_screen():
    settle_attempted = set()
    recovery_attempted = set()

    assert AutopilotSuiteService._claim_transient_launch_settle_attempt(
        "case-001", "screen-001", settle_attempted
    ) is True
    assert AutopilotSuiteService._claim_transient_launch_settle_attempt(
        "case-001", "screen-001", settle_attempted
    ) is False
    assert AutopilotSuiteService._claim_transient_launch_settle_attempt(
        "case-001", "screen-002", settle_attempted
    ) is True
    assert AutopilotSuiteService._claim_transient_launch_settle_attempt(
        "case-002", "screen-001", settle_attempted
    ) is True

    assert AutopilotSuiteService._claim_transient_launch_recovery_attempt(
        "case-001", "screen-001", recovery_attempted
    ) is True
    assert AutopilotSuiteService._claim_transient_launch_recovery_attempt(
        "case-001", "screen-001", recovery_attempted
    ) is False
    assert AutopilotSuiteService._claim_transient_launch_recovery_attempt(
        "case-002", "screen-001", recovery_attempted
    ) is True


def test_generic_startup_screen_failure_stays_local_to_its_case():
    generic_startup = (
        "The app remained on a generic startup screen after a verified relaunch. "
        "No guessed control was tapped and no screen case was attempted."
    )
    android_system_ui = (
        "Runtime session reached only Android system UI; the uploaded application was not launched."
    )

    assert not AutopilotSuiteService._is_target_foreground_failure(generic_startup)
    assert AutopilotSuiteService._is_target_foreground_failure(android_system_ui)


def test_device_farm_prompt_reset_preserves_sanitized_provider_reason():
    class Driver:
        def remove_app(self, _package):
            return None

        def is_app_installed(self, _package):
            return False

    class DeviceFarm:
        def install_app_in_session(self, *_args):
            error = RuntimeError("private provider response")
            error.safe_reason = (
                "AWS Device Farm could not reinstall the selected app upload "
                "(aws_error_code=AccessDeniedException http_status=403)."
            )
            raise error

    class Session:
        arn = "arn:remote-session"
        app_arn = "arn:uploaded-app"

    with pytest.raises(ProviderLifecycleUnavailable, match="aws_error_code=AccessDeniedException") as captured:
        AutopilotSuiteService._reset_device_farm_prompt_state(
            Driver(),
            "com.qtx.demo",
            DeviceFarm(),
            Session(),
            close_driver=lambda: None,
        )
    assert "private provider response" not in str(captured.value)
