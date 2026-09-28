"""Regression for FH Money's staged, initially-disabled sign-in controls."""
from pathlib import Path
from types import SimpleNamespace
import sys
import types
from xml.sax.saxutils import quoteattr

import pytest

from app.schemas.autopilot import AutopilotDiscoveryRequest
from app.services.autopilot_discovery import AutopilotDiscoveryService


class StagedLoginDriver:
    capabilities = {"appium:appPackage": "com.qtx.demo", "appium:appActivity": ".MainActivity"}

    def __init__(self, *, enable_submit=True, text_only_label=False, require_focus=False):
        self.state = "username"
        self.values = {}
        self.keyboard_visible = False
        self.enable_submit = enable_submit
        self.text_only_label = text_only_label
        self.require_focus = require_focus
        self.focused = False
        self.disable_field_after_entry = False
        self.ignore_set_text = False
        self.unsupported_keyboard = False
        self.keyboard_calls = []
        self.clear_blurs_focus = False
        self.ignore_keyboard_type = False
        self.semantic_button_not_clickable = False
        self.native_username_click_ignored = False
        self.transition_delay_reads = 0
        self.pending_state = None
        self.delay_remaining = 0
        self.gesture_calls = 0
        self.submitted = []
        self.quit_called = False
        self.persisted_states = []

    @property
    def page_source(self):
        if self.pending_state is not None:
            if self.delay_remaining:
                self.delay_remaining -= 1
            else:
                self.state = self.pending_state
                self.pending_state = None
        if self.state == "home":
            body = '<node text="Dashboard" class="android.widget.TextView" />'
        else:
            label = "Username / Email Address *" if self.state == "username" else "Password"
            value = self.values.get(self.state, "")
            enabled = bool(value and not self.keyboard_visible and self.enable_submit)
            body = (
                f'<node class="android.widget.EditText" content-desc={quoteattr(label)} '
                f'resource-id="com.qtx.demo:id/{self.state}" text={quoteattr(value)} '
                'clickable="true" enabled="true" />'
                f'<node class="android.widget.Button" content-desc="Continue" '
                f'clickable="{str(enabled).lower()}" enabled="{str(enabled).lower()}" />'
            )
            if self.text_only_label:
                # FH Money/Flutter exposes the empty input label as text,
                # replacing it with the value once Appium fills the widget.
                body = (
                    f'<node class="android.widget.EditText" text={quoteattr(value or label)} '
                    'clickable="true" enabled="true" />'
                    f'<node class="android.widget.Button" content-desc="Continue" '
                    f'clickable="{str(enabled).lower()}" enabled="{str(enabled).lower()}" />'
                )
            if value and self.disable_field_after_entry:
                body = body.replace('clickable="true" enabled="true"', 'clickable="true" enabled="false"', 1)
            if self.semantic_button_not_clickable:
                body = body.replace(f'clickable="{str(enabled).lower()}" enabled="{str(enabled).lower()}" />',
                                    f'clickable="false" enabled="{str(enabled).lower()}" />')
        return '<hierarchy><node package="com.qtx.demo" class="android.widget.FrameLayout">' + body + '</node></hierarchy>'

    def find_element(self, by, value):
        driver = self

        class Element:
            id = "observed-continue-element"

            def clear(self):
                driver.values[driver.state] = ""
                if driver.clear_blurs_focus:
                    driver.focused = False

            def send_keys(self, text):
                if not driver.ignore_set_text and (not driver.require_focus or driver.focused):
                    driver.values[driver.state] = text
                driver.keyboard_visible = True

            def get_attribute(self, name):
                return driver.values.get(driver.state, "") if name == "text" else None

            def click(self):
                if value != "Continue":
                    driver.focused = True
                    return
                assert value == "Continue"
                assert driver.values.get(driver.state) and not driver.keyboard_visible
                assert driver.enable_submit
                if driver.state == "username" and driver.native_username_click_ignored:
                    return
                driver.submitted.append(driver.state)
                next_state = "password" if driver.state == "username" else "home"
                if driver.transition_delay_reads:
                    driver.pending_state = next_state
                    driver.delay_remaining = driver.transition_delay_reads
                else:
                    driver.state = next_state
                driver.focused = False

        return Element()

    def execute_script(self, script, arguments):
        if script == "mobile: clickGesture":
            assert arguments == {"elementId": "observed-continue-element"}
            assert self.state == "username" and self.semantic_button_not_clickable
            self.gesture_calls += 1
            self.submitted.append(self.state)
            self.state = "password"
            self.focused = False
            return
        assert script == "mobile: type"
        if self.unsupported_keyboard:
            raise RuntimeError("Unknown mobile command")
        assert self.focused
        self.keyboard_calls.append(self.state)
        if not self.ignore_keyboard_type:
            self.values[self.state] = arguments["text"]
        self.keyboard_visible = True

    def hide_keyboard(self):
        self.keyboard_visible = False

    def get_screenshot_as_file(self, path):
        self.persisted_states.append((self.state, dict(self.values)))
        Path(path).write_bytes(b"test-only-image")
        return True

    def quit(self):
        self.quit_called = True


@pytest.fixture
def mobile_discovery(monkeypatch, tmp_path):
    driver = StagedLoginDriver()

    class AppiumBy:
        ACCESSIBILITY_ID = "accessibility id"
        ID = "id"
        XPATH = "xpath"

    class Options:
        def load_capabilities(self, _capabilities):
            return self

    appium = types.ModuleType("appium")
    webdriver = types.ModuleType("appium.webdriver")
    webdriver.Remote = lambda *_args, **_kwargs: driver
    appium.webdriver = webdriver
    by_module = types.ModuleType("appium.webdriver.common.appiumby")
    by_module.AppiumBy = AppiumBy
    android_options = types.ModuleType("appium.options.android")
    android_options.UiAutomator2Options = Options
    ios_options = types.ModuleType("appium.options.ios")
    ios_options.XCUITestOptions = Options
    for name, module in {
        "appium": appium,
        "appium.webdriver": webdriver,
        "appium.webdriver.common": types.ModuleType("appium.webdriver.common"),
        "appium.webdriver.common.appiumby": by_module,
        "appium.options": types.ModuleType("appium.options"),
        "appium.options.android": android_options,
        "appium.options.ios": ios_options,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr("app.services.autopilot_discovery.time.sleep", lambda _seconds: None)
    prototype = SimpleNamespace(_job_dir=lambda _job_id: tmp_path)
    service = AutopilotDiscoveryService(
        SimpleNamespace(AUTOPILOT_DISCOVERY_SETTLE_SECONDS=1, AUTOPILOT_DISCOVERY_SETTLE_RETRIES=0), prototype,
    )

    def run():
        return service._run_sync(
            "live-auth", "https://example.test/appium", "uploaded-app",
            AutopilotDiscoveryRequest(max_screens=8, max_actions=12),
            "com.qtx.demo", ".MainActivity", None, 30000, 30000, 30000,
            {"__auth_approved": "1", "__username": "synthetic-user@example.test", "__password": "synthetic-secret"},
        )

    return driver, run, tmp_path


def test_staged_login_refreshes_submit_after_each_credential_fill(mobile_discovery):
    driver, run, tmp_path = mobile_discovery
    result = run()

    assert driver.submitted == ["username", "password"]
    assert any(control.semantic_label == "Dashboard" for screen in result["screens"] for control in screen.controls)
    assert result["actions_attempted"] == 2
    assert driver.quit_called
    # No filled credential screen may be captured as screenshot/XML evidence.
    assert all(state == "home" or not values for state, values in driver.persisted_states)
    serialized = str(result)
    for path in tmp_path.rglob("*.xml"):
        serialized += path.read_text(encoding="utf-8")
    assert "synthetic-secret" not in serialized
    assert "synthetic-user@example.test" not in serialized


def test_flutter_text_only_login_label_survives_post_fill_redaction(mobile_discovery):
    driver, run, tmp_path = mobile_discovery
    driver.text_only_label = True
    result = run()

    assert driver.submitted == ["username", "password"]
    assert any(control.semantic_label == "Dashboard" for screen in result["screens"] for control in screen.controls)
    assert all(state == "home" or not values for state, values in driver.persisted_states)
    serialized = str(result) + "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.xml"))
    assert "synthetic-secret" not in serialized
    assert "synthetic-user@example.test" not in serialized


def test_disabled_continue_still_grounds_a_single_username_checkpoint():
    driver = StagedLoginDriver()
    controls = AutopilotDiscoveryService.parse_controls(driver.page_source)
    # Mirrors older stored maps whose email input was treated as test data.
    for control in controls:
        if control.input_capable:
            control.input_kind = "test_data"
    normalized = AutopilotDiscoveryService._ensure_auth_input_semantics(controls)
    assert normalized[0].input_kind == "credential"
    assert AutopilotDiscoveryService._auth_submit_control(normalized) is None
    assert AutopilotDiscoveryService._auth_submit_control(normalized, include_disabled=True) is not None


def test_flutter_credential_input_is_focused_before_entry(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.text_only_label = True
    driver.require_focus = True
    run()
    assert driver.submitted == ["username", "password"]


def test_enabled_submit_keeps_auth_identity_when_filled_field_is_disabled(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.text_only_label = True
    driver.disable_field_after_entry = True
    run()
    assert driver.submitted == ["username", "password"]


def test_flutter_uses_keyboard_events_when_native_set_text_is_ignored(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.text_only_label = True
    driver.ignore_set_text = True
    run()
    assert driver.keyboard_calls == ["username", "password"]
    assert driver.submitted == ["username", "password"]


def test_unsupported_keyboard_extension_falls_back_to_standard_entry(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.unsupported_keyboard = True
    run()
    assert driver.keyboard_calls == []
    assert driver.submitted == ["username", "password"]


def test_credential_clear_restores_focus_before_keyboard_entry(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.clear_blurs_focus = True
    driver.require_focus = True
    run()
    assert driver.submitted == ["username", "password"]


def test_silent_keyboard_delivery_failure_replaces_observed_username(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.ignore_keyboard_type = True
    result = run()
    assert driver.submitted == ["username"]
    assert driver.values["username"] == "synthetic-user@example.test"
    assert result["authentication_blocked"] is True
    assert "synthetic-user@example.test" not in str(result)


def test_duplicate_screen_merge_refreshes_enabled_state():
    from app.schemas.autopilot import DiscoveredScreen

    driver = StagedLoginDriver()
    old = AutopilotDiscoveryService.parse_controls(driver.page_source)
    screen = DiscoveredScreen(screen_id="login", fingerprint="login", controls=old)
    driver.values["username"] = "synthetic-user@example.test"
    current = AutopilotDiscoveryService.parse_controls(driver.page_source)
    AutopilotDiscoveryService._merge_screen_controls(screen, current)
    assert AutopilotDiscoveryService._auth_submit_control(screen.controls) is not None


def test_enabled_semantic_continue_with_false_clickable_is_normally_clicked(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.semantic_button_not_clickable = True
    result = run()
    assert driver.submitted == ["username", "password"]
    assert result["authentication_blocked"] is False
    assert any(control.semantic_label == "Dashboard" for screen in result["screens"] for control in screen.controls)


def test_username_continue_waits_for_delayed_observed_password_screen(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.semantic_button_not_clickable = True
    driver.transition_delay_reads = 3
    result = run()
    assert driver.submitted == ["username", "password"]
    assert driver.gesture_calls == 0
    assert result["authentication_blocked"] is False


def test_stuck_semantic_username_continue_uses_one_observed_element_gesture(mobile_discovery):
    driver, run, tmp_path = mobile_discovery
    driver.semantic_button_not_clickable = True
    driver.native_username_click_ignored = True
    result = run()
    assert driver.gesture_calls == 1
    assert driver.submitted == ["username", "password"]
    assert result["actions_attempted"] == 3
    assert result["authentication_blocked"] is False
    assert all(state == "home" or not values for state, values in driver.persisted_states)
    serialized = str(result) + "".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.xml"))
    assert "synthetic-secret" not in serialized
    assert "synthetic-user@example.test" not in serialized


def test_disabled_semantic_button_remains_unsubmitted(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.semantic_button_not_clickable = True
    driver.enable_submit = False
    result = run()
    assert driver.submitted == []
    assert result["authentication_blocked"] is True


def test_nonclickable_static_continue_is_not_an_auth_action():
    controls = AutopilotDiscoveryService.parse_controls('''<hierarchy>
        <node class="android.widget.EditText" content-desc="Username" enabled="true" />
        <node class="android.widget.TextView" content-desc="Continue" enabled="true" clickable="false" />
    </hierarchy>''')
    assert AutopilotDiscoveryService._auth_submit_control(controls) is None


def test_auth_submit_that_remains_disabled_is_not_clicked(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.enable_submit = False
    result = run()

    assert driver.submitted == []
    assert "did not become enabled" in result["stop_reason"]
    assert result["authentication_blocked"] is True
    assert "user_id_entry_confirmed=True" in result["warnings"][0]
    assert "synthetic-user@example.test" not in str(result)
    assert driver.quit_called


def test_auth_block_status_does_not_depend_on_message_wording(monkeypatch, tmp_path):
    import asyncio
    from app.schemas.autopilot import DiscoveredScreen

    app_file = tmp_path / "sample.apk"
    app_file.write_bytes(b"synthetic artifact")

    async def load_job(_job_id):
        return {"apk_path": str(app_file), "target_kind": "android"}

    async def load_analysis(_job_id):
        return SimpleNamespace(package_name="com.qtx.demo", main_activity=".MainActivity")

    async def stop_session(*args):
        pass

    prototype = SimpleNamespace(
        load_job=load_job, load_analysis=load_analysis,
        resolve_appium_url=lambda _request: "https://example.test/appium",
        _stop_device_farm_session=stop_session,
    )
    settings = SimpleNamespace(
        AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS=30,
        AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS=30,
    )
    service = AutopilotDiscoveryService(settings, prototype)
    monkeypatch.setattr(service, "_run_sync", lambda *args: {
        "screens": [DiscoveredScreen(screen_id="login", fingerprint="login")],
        "transitions": [], "actions_attempted": 1, "warnings": [],
        "stop_reason": "A newly worded validation message", "target_ready": True,
        "authentication_blocked": True,
    })
    result = asyncio.run(service.run("job", AutopilotDiscoveryRequest(provider="appium")))
    assert result.status == "partial"
