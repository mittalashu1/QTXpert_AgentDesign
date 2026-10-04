import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from app.schemas.autopilot import AutopilotDiscoveryRequest, DiscoveredControl, DiscoveryLocator
from app.services.autopilot_discovery import AutopilotDiscoveryService


SAMPLE_XML = '''
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" clickable="false" enabled="true">
    <node index="0" text="Sign in" resource-id="com.qtx:id/login" class="android.widget.Button" clickable="true" enabled="true" bounds="[10,10][200,80]" />
    <node index="1" text="Transfer money" resource-id="com.qtx:id/transfer" class="android.widget.Button" clickable="true" enabled="true" bounds="[10,90][200,160]" />
    <node index="2" text="" content-desc="Settings" resource-id="com.qtx:id/settings" class="android.widget.ImageButton" clickable="true" enabled="true" bounds="[210,10][260,60]" />
    <node index="3" text="Username" resource-id="com.qtx:id/username" class="android.widget.EditText" clickable="true" enabled="true" bounds="[10,180][300,240]" />
  </node>
</hierarchy>
'''

def test_runtime_prompt_parser_captures_observed_location_choices(tmp_path):
    class Driver:
        current_activity = "com.google.android.location.settings.LocationSettingsCheckerActivity"

        def get_screenshot_as_file(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"png")
            return True

    source = (
        '<hierarchy><node package="com.google.android.gms" text="Location settings" '
        'class="android.widget.FrameLayout">'
        '<node package="com.google.android.gms" text="Turn on" '
        'resource-id="com.google.android.gms:id/positive_button" '
        'class="android.widget.Button" clickable="true" enabled="true" />'
        '<node package="com.google.android.gms" text="No thanks" '
        'resource-id="com.google.android.gms:id/negative_button" '
        'class="android.widget.Button" clickable="true" enabled="true" />'
        '</node></hierarchy>'
    )

    prompt = AutopilotDiscoveryService._runtime_prompt_observation(
        Driver(), source, tmp_path, "android"
    )

    assert prompt is not None
    assert prompt.kind == "location_settings"
    assert [(choice.label, choice.decision) for choice in prompt.choices] == [
        ("Turn on", "allow"),
        ("No thanks", "deny"),
    ]
    assert all(choice.locators for choice in prompt.choices)
    assert prompt.screenshot_path
    assert prompt.page_source_path



def test_runtime_prompt_id_distinguishes_same_kind_with_different_prompt_copy(tmp_path):
    class Driver:
        current_activity = "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"

        def get_screenshot_as_file(self, path):
            Path(path).write_bytes(b"png")
            return True

    def prompt_source(permission_label):
        return (
            '<hierarchy><node package="com.android.permissioncontroller" '
            'class="android.widget.FrameLayout">'
            f'<node package="com.android.permissioncontroller" text="{permission_label}" '
            'class="android.widget.TextView" />'
            '<node package="com.android.permissioncontroller" text="Don\'t allow" '
            'resource-id="com.android.permissioncontroller:id/deny_button" '
            'class="android.widget.Button" clickable="true" enabled="true" />'
            '<node package="com.android.permissioncontroller" text="Allow while using the app" '
            'resource-id="com.android.permissioncontroller:id/allow_button" '
            'class="android.widget.Button" clickable="true" enabled="true" />'
            '</node></hierarchy>'
        )

    location = AutopilotDiscoveryService._runtime_prompt_observation(
        Driver(), prompt_source("Location permission"), tmp_path, "android"
    )
    camera = AutopilotDiscoveryService._runtime_prompt_observation(
        Driver(), prompt_source("Camera permission"), tmp_path, "android"
    )

    assert location is not None and camera is not None
    assert location.kind == camera.kind == "runtime_permission"
    assert location.prompt_id != camera.prompt_id


LABELLED_LOGIN_XML = '''
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" clickable="false" enabled="true">
    <node index="0" text="User ID" class="android.view.View" clickable="false" enabled="true" />
    <node index="1" text="(Email address)" class="android.view.View" clickable="false" enabled="true" />
    <node index="2" text="*" class="android.view.View" clickable="false" enabled="true" />
    <node index="3" text="" class="android.widget.EditText" clickable="true" enabled="true" bounds="[10,100][300,150]" />
    <node index="4" text="Password" class="android.view.View" clickable="false" enabled="true" />
    <node index="5" text="*" class="android.view.View" clickable="false" enabled="true" />
    <node index="6" text="" class="android.widget.EditText" clickable="true" enabled="true" bounds="[10,200][300,250]" />
  </node>
</hierarchy>
'''

GENERIC_LOGIN_XML = '''
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" clickable="false" enabled="true">
    <node index="0" text="" class="android.widget.EditText" clickable="true" enabled="true" resource-id="com.qtx:id/field_1" bounds="[10,100][300,150]" />
    <node index="1" text="" class="android.widget.EditText" clickable="true" enabled="true" resource-id="com.qtx:id/field_2" bounds="[10,200][300,250]" />
    <node index="2" text="Continue" class="android.widget.Button" clickable="true" enabled="true" resource-id="com.qtx:id/continue" bounds="[10,280][300,340]" />
  </node>
</hierarchy>
'''

GENERIC_SUBMIT_LOGIN_XML = '''
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" clickable="false" enabled="true">
    <node index="0" text="" class="android.widget.EditText" clickable="true" enabled="true" resource-id="com.qtx:id/field_1" bounds="[10,100][300,150]" />
    <node index="1" text="" class="android.widget.EditText" clickable="true" enabled="true" resource-id="com.qtx:id/field_2" bounds="[10,200][300,250]" />
    <node index="2" text="Submit" class="android.widget.Button" clickable="true" enabled="true" resource-id="com.qtx:id/submit" bounds="[10,280][300,340]" />
  </node>
</hierarchy>
'''

SCROLLABLE_XML = '''
<hierarchy rotation="0">
  <node index="0" class="android.widget.ScrollView" scrollable="true" enabled="true"
        resource-id="com.qtx:id/content" bounds="[0,0][1080,1920]" />
</hierarchy>
'''


def test_parse_controls_builds_semantics_and_locator_candidates():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    by_label = {control.semantic_label: control for control in controls}

    assert "Sign in" in by_label
    assert by_label["Sign in"].risk == "safe"
    assert by_label["Sign in"].locators[0].strategy == "id"
    assert by_label["Settings"].locators[0].strategy == "accessibility_id"
    assert by_label["Username"].input_capable is True
    assert by_label["Username"].input_kind == "credential"
    assert by_label["Username"].text == ""


def test_parse_controls_marks_scrollable_surfaces_for_bounded_traversal():
    controls = AutopilotDiscoveryService.parse_controls(SCROLLABLE_XML)

    assert len(controls) == 1
    assert controls[0].scrollable is True
    assert controls[0].semantic_label == "Scrollable content"
    # The container is observed as a reviewable surface; traversal invokes the
    # bounded gesture directly rather than clicking the container as a safe
    # business control.
    assert controls[0].risk == "review"
    assert controls[0].locators


def test_runtime_input_requests_are_reference_only():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="fp",
        package_name="com.qtx",
        activity_name=".MainActivity",
        controls=controls,
    )
    requests = AutopilotDiscoveryService.runtime_input_requests([screen])
    assert len(requests) == 1
    assert requests[0].source == "runtime"
    assert requests[0].category == "credential"
    assert requests[0].sensitive is True
    assert requests[0].field_type == "credential"
    assert requests[0].reference_present is False
    assert "username" in requests[0].label.lower()
    assert requests[0].question
    assert "user id" in requests[0].question.lower()
    assert requests[0].placeholder
    assert requests[0].format_hint


def test_runtime_checkpoint_keeps_observed_screen_evidence_reference():
    from uuid import UUID
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-evidence",
        fingerprint="e" * 64,
        screenshot_asset_id=UUID("11111111-1111-1111-1111-111111111111"),
        page_source_asset_id=UUID("22222222-2222-2222-2222-222222222222"),
        controls=[DiscoveredControl(
            control_id="email",
            semantic_label="Email",
            class_name="android.widget.EditText",
            input_capable=True,
            input_kind="credential",
            locators=[DiscoveryLocator(strategy="id", value="com.qtx:id/email", confidence=0.95)],
        )],
    )

    request = AutopilotDiscoveryService.runtime_input_requests([screen])[0]
    assert str(request.screenshot_asset_id) == "11111111-1111-1111-1111-111111111111"
    assert str(request.page_source_asset_id) == "22222222-2222-2222-2222-222222222222"


def test_runtime_input_requests_auto_select_bounded_synthetic_data_for_public_fields():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-public-form",
        fingerprint="public-form",
        controls=[
            DiscoveredControl(
                control_id="address",
                semantic_label="Address line 1",
                class_name="android.widget.EditText",
                input_capable=True,
                input_kind="test_data",
                locators=[DiscoveryLocator(strategy="id", value="com.qtx:id/address", confidence=0.95)],
            ),
        ],
    )

    requests = AutopilotDiscoveryService.runtime_input_requests([screen])

    assert len(requests) == 1
    assert requests[0].category == "test_data"
    assert requests[0].sensitive is False
    assert requests[0].status == "random"
    assert requests[0].reference_present is True
    assert "bounded synthetic" in requests[0].reason.lower()


def test_runtime_input_requests_use_accessibility_sibling_labels():
    controls = AutopilotDiscoveryService.parse_controls(LABELLED_LOGIN_XML)

    assert [control.semantic_label for control in controls if control.input_capable] == [
        "(Email address)",
        "Password",
    ]
    assert [control.input_kind for control in controls if control.input_capable] == [
        "credential",
        "credential",
    ]


def test_unlabelled_login_fields_are_promoted_to_user_id_and_password():
    controls = AutopilotDiscoveryService.parse_controls(GENERIC_LOGIN_XML)
    normalized = AutopilotDiscoveryService._ensure_auth_input_semantics(controls)
    inputs = [control for control in normalized if control.input_capable]

    assert [control.semantic_label for control in inputs] == ["User ID / email", "Password"]
    assert [control.input_kind for control in inputs] == ["credential", "credential"]


def test_ambiguous_generic_submit_does_not_guess_authentication():
    controls = AutopilotDiscoveryService.parse_controls(GENERIC_SUBMIT_LOGIN_XML)
    normalized = AutopilotDiscoveryService._ensure_auth_input_semantics(controls)
    inputs = [control for control in normalized if control.input_capable]

    # Resource IDs are retained as readable labels for ambiguous fields, but
    # their semantics must remain ordinary text (not guessed credentials).
    assert [control.semantic_label for control in inputs] == ["field 1", "field 2"]
    assert [control.input_kind for control in inputs] == ["test_data", "test_data"]
    assert AutopilotDiscoveryService._auth_submit_control(normalized) is None


def test_generic_continue_with_public_search_field_is_not_authentication():
    controls = [
        DiscoveredControl(
            control_id="search",
            semantic_label="Search",
            class_name="android.widget.EditText",
            input_capable=True,
            input_kind="test_data",
            locators=[DiscoveryLocator(strategy="id", value="com.qtx:id/search", confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="continue",
            semantic_label="Continue",
            class_name="android.widget.Button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="id", value="com.qtx:id/continue", confidence=0.95)],
        ),
    ]

    assert AutopilotDiscoveryService._auth_submit_control(controls) is None
    assert AutopilotDiscoveryService._ensure_auth_input_semantics(controls)[0].input_kind == "test_data"


def test_loading_screen_detection_is_conservative():
    from app.schemas.autopilot import DiscoveredScreen

    loading = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="fp",
        activity_name="LaunchScreen",
        controls=[],
    )
    assert AutopilotDiscoveryService._looks_like_loading_screen(loading) is True

    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    ready = DiscoveredScreen(screen_id="screen-002", fingerprint="fp2", controls=controls)
    assert AutopilotDiscoveryService._looks_like_loading_screen(ready) is False


def test_generic_unlocated_launch_view_is_not_treated_as_a_ready_screen():
    from app.schemas.autopilot import DiscoveredScreen

    splash = DiscoveredScreen(
        screen_id="screen-splash",
        fingerprint="splash",
        activity_name="com.example.investnation.MainActivity",
        controls=[
            DiscoveredControl(
                control_id="root-view",
                semantic_label="View",
                class_name="android.view.View",
                clickable=True,
                locators=[],
            )
        ],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(splash) is True


def test_transactional_control_is_blocked_before_navigation():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    transfer = next(control for control in controls if control.semantic_label == "Transfer money")

    assert transfer.risk == "blocked"
    assert transfer.risk_reason
    safe = AutopilotDiscoveryService._select_safe_control(controls, set())
    assert safe is not None
    assert safe.semantic_label in {"Sign in", "Settings"}


def test_text_only_login_cta_is_reachable_for_auth_checkpoint():
    controls = AutopilotDiscoveryService.parse_controls(
        '''
        <hierarchy rotation="0">
          <node index="0" class="android.widget.FrameLayout" clickable="false" enabled="true">
            <node index="0" text="Login" class="android.widget.TextView" clickable="true" enabled="true" bounds="[10,10][200,80]" />
          </node>
        </hierarchy>
        '''
    )

    login = AutopilotDiscoveryService._select_safe_control(controls, set())

    assert login is not None
    assert login.semantic_label == "Login"
    assert max(locator.confidence for locator in login.locators) == pytest.approx(0.82)


def test_persisted_mobile_hierarchy_redacts_input_values():
    source = (
        '<hierarchy><node class="android.widget.EditText" text="qa@example.test" '
        'value="qa@example.test" password="hunter2" content-desc="User ID" /></hierarchy>'
    )
    redacted = AutopilotDiscoveryService._redact_page_source(source)
    assert "qa@example.test" not in redacted
    assert "hunter2" not in redacted
    assert "User ID" in redacted


def test_screen_fingerprint_ignores_control_order():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    first = AutopilotDiscoveryService.fingerprint("com.qtx", ".MainActivity", controls)
    second = AutopilotDiscoveryService.fingerprint("com.qtx", ".MainActivity", list(reversed(controls)))

    assert first == second


def test_discovery_request_is_bounded():
    with pytest.raises(ValidationError):
        AutopilotDiscoveryRequest(max_screens=121)
    with pytest.raises(ValidationError):
        AutopilotDiscoveryRequest(max_actions=301)

    request = AutopilotDiscoveryRequest(observe_only=True, max_screens=1, max_actions=0)
    assert request.observe_only is True
    assert request.max_actions == 0
    normal = AutopilotDiscoveryRequest()
    assert normal.max_screens == 120
    assert normal.max_actions == 300


@pytest.mark.asyncio
async def test_browserstack_discovery_does_not_resolve_custom_appium(tmp_path, monkeypatch):
    apk_path = tmp_path / "app.apk"
    apk_path.write_bytes(b"apk")

    class Prototype:
        async def load_job(self, _job_id):
            return {"apk_path": str(apk_path), "filename": "app.apk"}

        async def load_analysis(self, _job_id):
            return SimpleNamespace(
                sha256="abc", app_name="Demo", package_name="com.qtx.demo", main_activity=".MainActivity"
            )

        async def _browserstack_app_url(self, _job_id, _apk_path, _sha256):
            return "bs://demo"

        def resolve_appium_url(self, _request):
            raise AssertionError("BrowserStack discovery must not resolve custom Appium")

        @staticmethod
        def _looks_like_connector_problem(_exc):
            return False

        async def _stop_device_farm_session(self, service, session):
            assert service is None and session is None

    settings = SimpleNamespace(
        BROWSERSTACK_HUB_URL="https://hub.browserstack.com/wd/hub",
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
        BROWSERSTACK_PROJECT_NAME="QTXpert",
        AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS=30,
        AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS=30,
    )
    service = AutopilotDiscoveryService(settings, Prototype())
    captured = {}

    def fake_run(*args):
        captured.update(url=args[1], app=args[2], options=args[6])
        return {
            "screens": [], "transitions": [], "actions_attempted": 0,
            "stop_reason": "Observed initial screen", "warnings": [],
        }

    monkeypatch.setattr(service, "_run_sync", fake_run)
    result = await service.run("job-1", AutopilotDiscoveryRequest(provider="browserstack"))

    assert result.status == "partial"
    assert captured["url"] == settings.BROWSERSTACK_HUB_URL
    assert captured["app"] == "bs://demo"
    assert captured["options"]["userName"] == "user"


@pytest.mark.asyncio
async def test_browserstack_upload_quota_is_returned_as_structured_blocker(tmp_path):
    apk_path = tmp_path / "app.apk"
    apk_path.write_bytes(b"apk")

    class Prototype:
        async def load_job(self, _job_id):
            return {"apk_path": str(apk_path), "filename": "app.apk"}

        async def load_analysis(self, _job_id):
            return SimpleNamespace(
                sha256="abc", app_name="Demo", package_name="com.qtx.demo", main_activity=".MainActivity"
            )

        async def _browserstack_app_url(self, _job_id, _apk_path, _sha256):
            raise RuntimeError("BrowserStack app upload failed (403): testing time expired")

        def resolve_appium_url(self, _request):
            raise AssertionError("BrowserStack discovery must not resolve custom Appium")

        @staticmethod
        def _looks_like_connector_problem(_exc):
            return True

        async def _stop_device_farm_session(self, service, session):
            assert service is None and session is None

    settings = SimpleNamespace(
        BROWSERSTACK_HUB_URL="https://hub.browserstack.com/wd/hub",
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
        BROWSERSTACK_PROJECT_NAME="QTXpert",
        AUTOPILOT_APPIUM_INSTALL_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_SERVER_LAUNCH_TIMEOUT_SECONDS=30,
        AUTOPILOT_APPIUM_ADB_EXEC_TIMEOUT_SECONDS=30,
        AUTOPILOT_DISCOVERY_TIMEOUT_SECONDS=30,
    )
    service = AutopilotDiscoveryService(settings, Prototype())

    result = await service.run("job-1", AutopilotDiscoveryRequest(provider="browserstack"))

    assert result.status == "blocked"
    assert result.target_ready is False
    assert "testing time expired" in (result.error or "")
    assert "testing time expired" in (result.target_identity_reason or "")

@pytest.mark.parametrize("deny_click_returns", [True, False])
def test_runtime_discovery_crawls_followup_location_prompt_then_stops_at_login(tmp_path, monkeypatch, deny_click_returns):
    import sys
    import types

    class AppiumBy:
        ACCESSIBILITY_ID = "accessibility id"
        ID = "id"
        XPATH = "xpath"

    class Options:
        def load_capabilities(self, _capabilities):
            return self

    class Element:
        def __init__(self, driver):
            self.driver = driver

        def __init__(self, driver, value):
            self.driver = driver
            self.value = value

        def is_enabled(self):
            return True

        def click(self):
            if self.value == "com.android.permissioncontroller:id/deny_button":
                self.driver.state = "location_prompt"
            elif self.value == "com.google.android.gms:id/negative_button":
                if self.driver.deny_click_returns:
                    self.driver.state = "landing"
            elif self.value == "com.qtx.demo:id/login":
                self.driver.state = "login"

    class Driver:
        capabilities = {"appium:appPackage": "com.qtx.demo", "appium:appActivity": ".MainActivity"}

        def __init__(self, deny_click_returns):
            self.state = "runtime_permission_prompt"
            self.quit_called = False
            self.back_calls = 0
            self.deny_click_returns = deny_click_returns

        @property
        def current_activity(self):
            if self.state == "runtime_permission_prompt":
                return "com.android.permissioncontroller.permission.ui.GrantPermissionsActivity"
            if self.state == "location_prompt":
                return "com.google.android.location.settings.LocationSettingsCheckerActivity"
            return "com.qtx.demo.MainActivity"

        @property
        def page_source(self):
            if self.state == "runtime_permission_prompt":
                return (
                    '<hierarchy><node package="com.android.permissioncontroller" '
                    'class="android.widget.FrameLayout">'
                    '<node package="com.android.permissioncontroller" text="Location permission" '
                    'class="android.widget.TextView" />'
                    '<node package="com.android.permissioncontroller" text="Don\'t allow" '
                    'resource-id="com.android.permissioncontroller:id/deny_button" '
                    'class="android.widget.Button" clickable="true" enabled="true" />'
                    '<node package="com.android.permissioncontroller" text="Allow while using the app" '
                    'resource-id="com.android.permissioncontroller:id/allow_button" '
                    'class="android.widget.Button" clickable="true" enabled="true" />'
                    '</node></hierarchy>'
                )
            if self.state == "location_prompt":
                return (
                    '<hierarchy><node package="com.google.android.gms" text="Location settings" '
                    'class="android.widget.FrameLayout">'
                    '<node package="com.google.android.gms" text="Turn on" '
                    'resource-id="com.google.android.gms:id/positive_button" '
                    'class="android.widget.Button" clickable="true" enabled="true" />'
                    '<node package="com.google.android.gms" text="No thanks" '
                    'resource-id="com.google.android.gms:id/negative_button" '
                    'class="android.widget.Button" clickable="true" enabled="true" />'
                    '</node></hierarchy>'
                )
            if self.state == "landing":
                return (
                    '<hierarchy><node package="com.qtx.demo" class="android.widget.FrameLayout">'
                    '<node package="com.qtx.demo" text="Welcome" class="android.widget.TextView" />'
                    '<node package="com.qtx.demo" text="Login" resource-id="com.qtx.demo:id/login" '
                    'class="android.widget.Button" clickable="true" enabled="true" />'
                    '</node></hierarchy>'
                )
            return (
                '<hierarchy><node package="com.qtx.demo" class="android.widget.FrameLayout">'
                '<node package="com.qtx.demo" text="User ID" class="android.widget.TextView" />'
                '<node package="com.qtx.demo" resource-id="com.qtx.demo:id/user" '
                'class="android.widget.EditText" clickable="true" enabled="true" />'
                '<node package="com.qtx.demo" text="Password" class="android.widget.TextView" />'
                '<node package="com.qtx.demo" resource-id="com.qtx.demo:id/password" '
                'class="android.widget.EditText" clickable="true" enabled="true" />'
                '<node package="com.qtx.demo" text="Sign in" resource-id="com.qtx.demo:id/signin" '
                'class="android.widget.Button" clickable="true" enabled="true" />'
                '</node></hierarchy>'
            )

        def back(self):
            self.back_calls += 1
            if self.state in {"runtime_permission_prompt", "location_prompt"}:
                self.state = "landing"

        def find_element(self, by, value):
            assert by == AppiumBy.ID
            assert value in {
                "com.android.permissioncontroller:id/deny_button",
                "com.android.permissioncontroller:id/allow_button",
                "com.google.android.gms:id/negative_button",
                "com.google.android.gms:id/positive_button",
                "com.qtx.demo:id/login",
            }
            return Element(self, value)

        def get_screenshot_as_file(self, path):
            Path(path).write_bytes(b"png")
            return True

        def quit(self):
            self.quit_called = True

    driver = Driver(deny_click_returns)
    appium = types.ModuleType("appium")
    webdriver = types.ModuleType("appium.webdriver")
    webdriver.Remote = lambda *_args, **_kwargs: driver
    appium.webdriver = webdriver
    appium_by_module = types.ModuleType("appium.webdriver.common.appiumby")
    appium_by_module.AppiumBy = AppiumBy
    android_options = types.ModuleType("appium.options.android")
    android_options.UiAutomator2Options = Options
    ios_options = types.ModuleType("appium.options.ios")
    ios_options.XCUITestOptions = Options
    for name, module in {
        "appium": appium,
        "appium.webdriver": webdriver,
        "appium.webdriver.common": types.ModuleType("appium.webdriver.common"),
        "appium.webdriver.common.appiumby": appium_by_module,
        "appium.options": types.ModuleType("appium.options"),
        "appium.options.android": android_options,
        "appium.options.ios": ios_options,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    fake_clock = {"now": 0.0}

    def advance_clock(seconds=0.25):
        fake_clock["now"] += max(0.01, float(seconds))

    def fake_monotonic():
        fake_clock["now"] += 0.01
        return fake_clock["now"]

    monkeypatch.setattr("app.services.autopilot_discovery.time.sleep", advance_clock)
    monkeypatch.setattr("app.services.autopilot_discovery.time.monotonic", fake_monotonic)

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    service = AutopilotDiscoveryService(
        SimpleNamespace(AUTOPILOT_DISCOVERY_SETTLE_SECONDS=1, AUTOPILOT_DISCOVERY_SETTLE_RETRIES=0),
        Prototype(),
    )
    request = AutopilotDiscoveryRequest(provider="browserstack", max_screens=8, max_actions=12)

    result = service._run_sync(
        "job-login-after-navigation",
        "https://hub.example.test/wd/hub",
        "bs://app",
        request,
        "com.qtx.demo",
        ".MainActivity",
        None,
        30_000,
        30_000,
        30_000,
    )

    assert result["stop_reason"].startswith("Authentication checkpoint detected.")
    assert result["actions_attempted"] == 3
    assert driver.back_calls == (0 if deny_click_returns else 1)
    permission_prompt = next(item for item in result["runtime_prompts"] if item.kind == "runtime_permission")
    location_prompt = next(item for item in result["runtime_prompts"] if item.kind == "location_settings")
    permission_denial = next(choice for choice in permission_prompt.choices if choice.decision == "deny")
    permission_allowance = next(choice for choice in permission_prompt.choices if choice.decision == "allow")
    location_denial = next(choice for choice in location_prompt.choices if choice.decision == "deny")
    assert permission_denial.outcome_status == "observed"
    assert permission_denial.resulting_prompt_id == location_prompt.prompt_id
    assert permission_denial.resulting_screen_id is None
    assert permission_allowance.outcome_status == "planned"
    assert location_denial.outcome_status == ("observed" if deny_click_returns else "unavailable")
    assert location_denial.resulting_screen_id == ("screen-001" if deny_click_returns else None)
    assert len(result["screens"]) == 2
    assert result["screens"][1].screen_id == "screen-002"
    assert {control.semantic_label for control in result["screens"][1].controls if control.input_capable} == {
        "User ID / email",
        "Password",
    }
    assert len(result["transitions"]) == 1
    assert driver.quit_called is True

def test_auth_entry_login_is_prioritized_over_higher_confidence_guest_route():
    controls = [
        DiscoveredControl(
            control_id="guest",
            semantic_label="Explore as a Guest",
            class_name="android.widget.Button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="id", value="Explore as a Guest", confidence=0.99)],
        ),
        DiscoveredControl(
            control_id="login",
            semantic_label="Login",
            class_name="android.widget.TextView",
            clickable=False,
            risk="safe",
            locators=[DiscoveryLocator(strategy="id", value="Login", confidence=0.82)],
        ),
    ]

    selected = AutopilotDiscoveryService._select_safe_control(controls, set())

    assert selected is not None
    assert selected.semantic_label == "Login"
    assert not AutopilotDiscoveryService._looks_like_loading_screen(
        SimpleNamespace(activity_name=".MainActivity", title="", controls=[controls[1]])
    )


@pytest.mark.parametrize("label", [
    "Home Tab 1 of 4",
    "Investments Tab 2 of 4",
    "Cards Tab 3 of 4",
    "Bullion Tab 4 of 4",
])
def test_native_safe_tab_position_suffix_is_not_treated_as_a_risky_action(label):
    risk, reason = AutopilotDiscoveryService._risk(label, {})

    assert risk == "safe"
    assert reason is None


def test_send_money_bottom_tab_is_mapped_only_when_transaction_journey_discovery_is_enabled():
    risk, reason = AutopilotDiscoveryService._risk("Send Money Tab 4 of 4", {})

    assert risk == "review"
    assert "map this screen only" in reason.lower()

    control = DiscoveredControl(
        control_id="send-money-tab",
        semantic_label="Send Money Tab 4 of 4",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        risk=risk,
        risk_reason=reason,
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Send Money", confidence=0.99)],
    )

    assert AutopilotDiscoveryService._select_safe_control([control], set()) is None
    selected = AutopilotDiscoveryService._select_safe_control(
        [control], set(), include_transaction_journeys=True
    )
    assert selected is control


def test_flutter_duplicate_login_label_prefers_clickable_action_when_semantics_are_not_clickable():
    class AppiumBy:
        ACCESSIBILITY_ID = "accessibility id"
        ID = "id"
        XPATH = "xpath"

    class Element:
        def __init__(self, clickable=False):
            self.clickable = clickable

        def get_attribute(self, name):
            return {
                "class": "android.view.View",
                "clickable": str(self.clickable).lower(),
                "enabled": "true",
            }.get(name)

    heading = Element()
    button = Element(clickable=True)

    class Driver:
        def find_elements(self, strategy, value):
            assert strategy == AppiumBy.ACCESSIBILITY_ID
            assert value == "Login"
            return [heading, button]

        def find_element(self, *_args):
            raise AssertionError("Ambiguous first-match lookup must not be used")

    login = DiscoveredControl(
        control_id="login-button",
        semantic_label="Login",
        class_name="android.view.View",
        clickable=False,
        enabled=True,
        input_capable=False,
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Login", confidence=0.99)],
    )

    resolved = AutopilotDiscoveryService._find_discovered_element(Driver(), login, AppiumBy)

    assert resolved is button



def test_auth_submit_prefers_native_button_over_duplicate_login_view():
    credential = DiscoveredControl(
        control_id="username",
        semantic_label="Username",
        class_name="android.widget.EditText",
        input_capable=True,
        input_kind="credential",
        locators=[DiscoveryLocator(strategy="id", value="username", confidence=0.99)],
    )
    view = DiscoveredControl(
        control_id="login-label",
        semantic_label="Login",
        class_name="android.view.View",
        clickable=True,
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Login", confidence=0.99)],
    )
    button = DiscoveredControl(
        control_id="login-button",
        semantic_label="Login",
        class_name="android.widget.Button",
        clickable=False,
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Login", confidence=0.99)],
    )

    assert AutopilotDiscoveryService._auth_submit_control([credential, view, button]) is button


def test_auth_submit_does_not_guess_between_equally_ranked_duplicate_buttons():
    credential = DiscoveredControl(
        control_id="username",
        semantic_label="Username",
        class_name="android.widget.EditText",
        input_capable=True,
        input_kind="credential",
        locators=[DiscoveryLocator(strategy="id", value="username", confidence=0.99)],
    )
    first = DiscoveredControl(
        control_id="login-button-a",
        semantic_label="Login",
        class_name="android.widget.Button",
        clickable=True,
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Login", confidence=0.99)],
    )
    second = first.model_copy(update={"control_id": "login-button-b"})

    assert AutopilotDiscoveryService._auth_submit_control([credential, first, second]) is None


@pytest.mark.parametrize("message", [
    "Your account credentials are temporarily blocked.",
    "Too many login attempts. Try again later.",
])
def test_auth_feedback_detects_temporary_account_lock_without_returning_copy(message):
    source = (
        '<hierarchy><node class="android.widget.TextView" '
        f'text="{message}" /></hierarchy>'
    )

    assert AutopilotDiscoveryService._auth_feedback_code(source) == "account_locked"





def test_loading_screen_treats_unlabelled_root_view_as_incomplete():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="launch-surface",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[DiscoveredControl(
            control_id="root-view",
            semantic_label="View",
            class_name="android.view.View",
            clickable=True,
            enabled=True,
        )],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is True


def test_discovery_preserves_incomplete_launch_status_instead_of_crawling_empty_surface(tmp_path, monkeypatch):
    import appium
    from app.config import Settings
    from app.schemas.autopilot import AutopilotDiscoveryRequest

    class Driver:
        capabilities = {
            "appium:appPackage": "com.qtx.demo",
            "appium:appActivity": "com.qtx.demo.MainActivity",
        }
        page_source = (
            '<hierarchy><node package="com.qtx.demo" '
            'class="android.view.View" text="" clickable="true" enabled="true" '
            'bounds="[0,0][1080,1920]" /></hierarchy>'
        )

        def get_screenshot_as_file(self, path):
            from pathlib import Path
            Path(path).write_bytes(b"screen")
            return True

        def quit(self):
            return None

    driver = Driver()
    monkeypatch.setattr(appium.webdriver, "Remote", lambda *args, **kwargs: driver)
    monkeypatch.setattr("app.services.autopilot_discovery.time.sleep", lambda _seconds: None)

    class Prototype:
        @staticmethod
        def _job_dir(_job_id):
            return tmp_path

    service = AutopilotDiscoveryService(
        Settings(AUTOPILOT_DISCOVERY_SETTLE_SECONDS=1, AUTOPILOT_DISCOVERY_SETTLE_RETRIES=1),
        Prototype(),
    )
    request = AutopilotDiscoveryRequest(
        target_kind="android",
        provider="devicefarm",
        device_name="Google Pixel 8",
    )

    result = service._run_sync(
        "job-123",
        "https://devicefarm.invalid/appium",
        "arn:uploaded-app",
        request,
        "com.qtx.demo",
        "com.qtx.demo.MainActivity",
        None,
        1000,
        1000,
        1000,
    )

    assert "non-interactive launch screen" in result["stop_reason"].lower()
    assert result["actions_attempted"] == 0
    assert result["transitions"] == []
    assert result["target_ready"] is True
    assert result["interactive_surface_ready"] is False
    assert "retry discovery" in result["checkpoint_message"].lower()

def test_loading_screen_ignores_generic_root_marked_as_input_capable():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="flutter-splash",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[DiscoveredControl(
            control_id="root-view",
            semantic_label="View",
            class_name="android.view.View",
            clickable=True,
            enabled=True,
            input_capable=True,
            locators=[DiscoveryLocator(strategy="id", value="root", confidence=0.9)],
        )],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is True


def test_loading_screen_accepts_a_real_safe_entry_point():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="real-entry",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[DiscoveredControl(
            control_id="sign-in",
            semantic_label="Sign in",
            class_name="android.widget.Button",
            clickable=True,
            enabled=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="accessibility_id", value="Sign in", confidence=0.99)],
        )],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is False


def test_loading_screen_keeps_a_scrollable_generic_flutter_root_incomplete():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="scrollable-landing",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[DiscoveredControl(
            control_id="content",
            semantic_label="ScrollView",
            class_name="android.widget.ScrollView",
            enabled=True,
            scrollable=True,
            locators=[DiscoveryLocator(strategy="id", value="content", confidence=0.95)],
        )],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is True


def test_loading_screen_treats_many_generic_nodes_as_incomplete():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="sparse-flutter-splash",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[
            DiscoveredControl(control_id=f"view-{index}", semantic_label="View", class_name="android.view.View")
            for index in range(6)
        ],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is True


def test_loading_screen_accepts_observed_credential_fields():
    from app.schemas.autopilot import DiscoveredScreen

    screen = DiscoveredScreen(
        screen_id="screen-001",
        fingerprint="login",
        package_name="com.qtx.demo",
        activity_name="com.qtx.demo.MainActivity",
        controls=[
            DiscoveredControl(
                control_id="username",
                semantic_label="User ID",
                class_name="android.widget.EditText",
                enabled=True,
                input_capable=True,
                input_kind="credential",
                locators=[DiscoveryLocator(strategy="id", value="username", confidence=0.99)],
            ),
            DiscoveredControl(
                control_id="password",
                semantic_label="Password",
                class_name="android.widget.EditText",
                enabled=True,
                input_capable=True,
                input_kind="credential",
                locators=[DiscoveryLocator(strategy="id", value="password", confidence=0.99)],
            ),
        ],
    )

    assert AutopilotDiscoveryService._looks_like_loading_screen(screen) is False


def test_startup_surface_diagnostic_reports_only_a_coarse_target_crash():
    class Driver:
        def get_log(self, log_type):
            assert log_type == "logcat"
            return [
                {"message": "FATAL EXCEPTION in com.qtx.demo: private crash detail"},
                {"message": "system_server FATAL EXCEPTION in unrelated.service"},
            ]

    diagnostic = AutopilotDiscoveryService._startup_surface_diagnostic(Driver(), "com.qtx.demo")

    assert diagnostic == "Startup diagnostics: the target app reported a launch crash."
    assert "private crash detail" not in diagnostic


@pytest.mark.parametrize(("message", "expected"), [
    ("com.qtx.demo: java.net.UnknownHostException", "Startup diagnostics: the target app could not reach a required service."),
    ("com.qtx.demo: MissingPluginException", "Startup diagnostics: Flutter reported an initialization error."),
])
def test_startup_surface_diagnostic_classifies_target_network_and_flutter_errors(message, expected):
    class Driver:
        def get_log(self, _log_type):
            return [{"message": message}]

    assert AutopilotDiscoveryService._startup_surface_diagnostic(Driver(), "com.qtx.demo") == expected


def test_startup_surface_diagnostic_ignores_unrelated_system_logs():
    class Driver:
        def get_log(self, _log_type):
            return [{"message": "system_server FATAL EXCEPTION in com.other.package"}]

    assert AutopilotDiscoveryService._startup_surface_diagnostic(Driver(), "com.qtx.demo") is None


def test_startup_surface_diagnostic_is_optional_when_provider_disables_logcat():
    class Driver:
        def get_log(self, _log_type):
            raise RuntimeError("provider does not expose device logs")

    assert AutopilotDiscoveryService._startup_surface_diagnostic(Driver(), "com.qtx.demo") is None



@pytest.mark.parametrize(
    ("label", "decision"),
    [
        ("Don't allow", "deny"),
        ("Don’t allow", "deny"),
        ("Do not allow", "deny"),
        ("No thanks", "deny"),
        ("Cancel", "deny"),
        ("Allow while using the app", "allow"),
        ("Turn on", "allow"),
    ],
)
def test_prompt_choice_decision_prioritizes_explicit_declines(label, decision):
    assert AutopilotDiscoveryService._prompt_choice_decision(label.lower()) == decision



@pytest.mark.parametrize("label", ["Precise", "Approximate"])
def test_location_accuracy_options_are_not_terminal_permission_decisions(label):
    assert AutopilotDiscoveryService._prompt_choice_decision(label.lower()) is None
