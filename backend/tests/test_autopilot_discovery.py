import pytest
from pydantic import ValidationError
from types import SimpleNamespace

from app.schemas.autopilot import AutopilotDiscoveryRequest
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


def test_transactional_control_is_blocked_before_navigation():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    transfer = next(control for control in controls if control.semantic_label == "Transfer money")

    assert transfer.risk == "blocked"
    assert transfer.risk_reason
    safe = AutopilotDiscoveryService._select_safe_control(controls, set())
    assert safe is not None
    assert safe.semantic_label in {"Sign in", "Settings"}


def test_screen_fingerprint_ignores_control_order():
    controls = AutopilotDiscoveryService.parse_controls(SAMPLE_XML)
    first = AutopilotDiscoveryService.fingerprint("com.qtx", ".MainActivity", controls)
    second = AutopilotDiscoveryService.fingerprint("com.qtx", ".MainActivity", list(reversed(controls)))

    assert first == second


def test_discovery_request_is_bounded():
    with pytest.raises(ValidationError):
        AutopilotDiscoveryRequest(max_screens=100)
    with pytest.raises(ValidationError):
        AutopilotDiscoveryRequest(max_actions=99)

    request = AutopilotDiscoveryRequest(observe_only=True, max_screens=1, max_actions=0)
    assert request.observe_only is True
    assert request.max_actions == 0


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

