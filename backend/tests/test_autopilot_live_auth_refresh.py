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

    def __init__(self, *, enable_submit=True):
        self.state = "username"
        self.values = {}
        self.keyboard_visible = False
        self.enable_submit = enable_submit
        self.submitted = []
        self.quit_called = False
        self.persisted_states = []

    @property
    def page_source(self):
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
        return '<hierarchy><node package="com.qtx.demo" class="android.widget.FrameLayout">' + body + '</node></hierarchy>'

    def find_element(self, by, value):
        driver = self

        class Element:
            def clear(self):
                driver.values[driver.state] = ""

            def send_keys(self, text):
                driver.values[driver.state] = text
                driver.keyboard_visible = True

            def click(self):
                assert value == "Continue"
                assert driver.values.get(driver.state) and not driver.keyboard_visible
                assert driver.enable_submit
                driver.submitted.append(driver.state)
                driver.state = "password" if driver.state == "username" else "home"

        return Element()

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


def test_duplicate_screen_merge_refreshes_enabled_state():
    from app.schemas.autopilot import DiscoveredScreen

    driver = StagedLoginDriver()
    old = AutopilotDiscoveryService.parse_controls(driver.page_source)
    screen = DiscoveredScreen(screen_id="login", fingerprint="login", controls=old)
    driver.values["username"] = "synthetic-user@example.test"
    current = AutopilotDiscoveryService.parse_controls(driver.page_source)
    AutopilotDiscoveryService._merge_screen_controls(screen, current)
    assert AutopilotDiscoveryService._auth_submit_control(screen.controls) is not None


def test_auth_submit_that_remains_disabled_is_not_clicked(mobile_discovery):
    driver, run, _ = mobile_discovery
    driver.enable_submit = False
    result = run()

    assert driver.submitted == []
    assert "sign-in control" in result["stop_reason"]
    assert driver.quit_called
