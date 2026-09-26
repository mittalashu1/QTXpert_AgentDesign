from types import SimpleNamespace

from app.api.routes.autopilot import _resume_should_run_discovery
from app.schemas.autopilot import DiscoveredControl, DiscoveredScreen, DiscoveryLocator
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_workflow import transition_phase


def test_checkpoint_resume_retries_partial_auth_discovery_after_approval():
    discovery = SimpleNamespace(
        status="partial",
        stop_reason="Credentials were supplied, but no safe sign-in control was found",
    )
    setup = SimpleNamespace(safe_authentication_approved=True)

    assert _resume_should_run_discovery(False, discovery, setup) is True


def test_checkpoint_resume_does_not_repeat_unrelated_or_unapproved_discovery():
    partial = SimpleNamespace(status="partial", stop_reason="No additional safe navigation controls were available")
    completed = SimpleNamespace(status="completed", stop_reason="Discovery completed")

    assert _resume_should_run_discovery(False, partial, SimpleNamespace(safe_authentication_approved=True)) is False
    assert _resume_should_run_discovery(
        False,
        SimpleNamespace(status="partial", stop_reason="Sign-in returned to the same screen"),
        SimpleNamespace(safe_authentication_approved=False),
    ) is False
    assert _resume_should_run_discovery(
        False,
        completed,
        SimpleNamespace(safe_authentication_approved=True),
    ) is False
    assert _resume_should_run_discovery(True, completed, None) is True
    assert _resume_should_run_discovery(False, None, None) is True


def test_source_reanalysis_can_restart_from_exploring_phase():
    assert transition_phase("exploring", "preflight") == "preflight"


def test_fh_money_single_username_step_remains_an_authentication_gate():
    controls = [
        DiscoveredControl(
            control_id="username-email",
            semantic_label="Username / Email Address *",
            class_name="android.widget.EditText",
            input_capable=True,
            input_kind="test_data",
            locators=[DiscoveryLocator(strategy="xpath", value='(//*[@class="android.widget.EditText"])[1]', confidence=0.95)],
        ),
        DiscoveredControl(
            control_id="continue",
            semantic_label="Continue",
            class_name="android.widget.Button",
            clickable=True,
            risk="safe",
            locators=[DiscoveryLocator(strategy="accessibility_id", value="Continue", confidence=0.99)],
        ),
    ]

    normalized = AutopilotDiscoveryService._ensure_auth_input_semantics(controls)
    screen = DiscoveredScreen(screen_id="screen-username", fingerprint="username", controls=normalized)
    request = AutopilotDiscoveryService.runtime_input_requests([screen])[0]

    assert AutopilotDiscoveryService._credential_controls(screen)[0].input_kind == "credential"
    assert AutopilotDiscoveryService._auth_submit_control(normalized).control_id == "continue"
    assert request.category == "credential"
    assert request.input_hint == "username"
    assert request.status == "pending"
