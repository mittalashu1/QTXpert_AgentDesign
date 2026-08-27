import pytest
from pydantic import ValidationError

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
