import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.routes import autopilot
from app.schemas.autopilot import AutopilotInputRequest, AutopilotSavedInput, AutopilotSetupProfile


@pytest.mark.parametrize("field_time,bundle_time,expected", [
    (None, None, "corrected-user@example.test"),
    ("2026-09-27T11:00:00Z", "2026-09-27T10:00:00Z", "corrected-user@example.test"),
    ("2026-09-27T10:00:00Z", "2026-09-27T11:00:00Z", "old-user@example.test"),
])
def test_corrected_runtime_credential_takes_precedence_over_old_bundle(monkeypatch, field_time, bundle_time, expected):
    async def resolve(*args, **kwargs):
        assert kwargs.get("job_id") == "job"
        return {
            "runtime_user": "corrected-user@example.test",
            "credential_reference": json.dumps({
                "username": "old-user@example.test", "password": "synthetic-secret",
            }),
        }.get(args[-1])

    monkeypatch.setattr(autopilot, "resolve_value", resolve)
    request = SimpleNamespace(
        key="runtime_user", category="credential", input_hint="username",
        label="User ID", sensitive=True,
    )
    setup = SimpleNamespace(
        input_requests=[], runtime_input_requests=[request], safe_authentication_approved=True,
        saved_inputs=[
            SimpleNamespace(key="runtime_user", updated_at=field_time),
            SimpleNamespace(key="credential_reference", updated_at=bundle_time),
        ],
    )
    record = SimpleNamespace(surface_key="fh-money", job_id="job", owner_id="owner", project_id="project")
    values, sensitive = asyncio.run(autopilot._resolve_discovery_input_values(None, None, record, setup))

    assert values["runtime_user"] == expected
    assert values["__username"] == expected
    assert values["__password"] == "synthetic-secret"
    assert "runtime_user" in sensitive
    assert "credential_reference" not in values


def test_disabled_sign_in_can_resume_after_corrected_input():
    discovery = SimpleNamespace(status="partial", stop_reason="The observed sign-in button did not become enabled")
    setup = SimpleNamespace(safe_authentication_approved=True)
    assert autopilot._resume_should_run_discovery(False, discovery, setup)


def test_mobile_replay_reuses_approved_login_without_consuming_a_one_time_code(monkeypatch):
    async def resolve(*args, **kwargs):
        assert not kwargs.get("consume")
        assert args[-1] != "runtime_otp"
        return json.dumps({
            "username": "qa@example.test", "password": "fixture-password", "otp": "fixture-otp",
        }) if args[-1] == "credential_reference" else None

    monkeypatch.setattr(autopilot, "resolve_value", resolve)
    setup = SimpleNamespace(
        input_requests=[], saved_inputs=[], safe_authentication_approved=True,
        runtime_input_requests=[SimpleNamespace(
            key="runtime_otp", category="credential", input_hint="otp", label="Verification code", sensitive=True,
        )],
    )
    record = SimpleNamespace(surface_key="fixture", job_id="job", owner_id="owner", project_id="project")

    values, _ = asyncio.run(autopilot._resolve_discovery_input_values(None, None, record, setup, consume_otp=False))

    assert values == {
        "__auth_approved": "1", "__username": "qa@example.test", "__password": "fixture-password",
    }


@pytest.mark.parametrize(
    ("bundle_job_id", "bundle_time", "expected_auth_approval"),
    [
        ("job", "2026-10-04T11:00:00Z", False),
        ("job", "2026-10-04T13:00:00Z", True),
        ("other-job", "2026-10-04T13:00:00Z", False),
    ],
)
def test_discovery_does_not_replay_rejected_credentials_without_a_new_value(
    monkeypatch, bundle_job_id, bundle_time, expected_auth_approval,
):
    async def resolve(*args, **kwargs):
        assert kwargs.get("job_id") == "job"
        return {
            "runtime_user": "saved-user@example.test",
            "credential_reference": json.dumps({
                "username": "saved-user@example.test", "password": "saved-secret",
            }),
        }.get(args[-1])

    monkeypatch.setattr(autopilot, "resolve_value", resolve)
    request = AutopilotInputRequest(
        key="runtime_user", category="credential", input_hint="username",
        label="User ID", sensitive=True, reason="Observed sign-in field.",
    )
    setup = AutopilotSetupProfile(
        job_id="job", runtime_input_requests=[request], safe_authentication_approved=True,
        saved_inputs=[
            AutopilotSavedInput(
                key="runtime_user", job_id="job", label="User ID", category="credential",
                decision="provide", has_value=True, updated_at="2026-10-04T11:00:00Z",
            ),
            AutopilotSavedInput(
                key="credential_reference", job_id=bundle_job_id, label="UAT sign-in credentials",
                category="credential", decision="provide", has_value=True, updated_at=bundle_time,
            ),
        ],
    )
    record = SimpleNamespace(surface_key="fh-money", job_id="job", owner_id="owner", project_id="project")
    discovery = SimpleNamespace(
        checkpoint_message="The app rejected the saved UAT sign-in details; no further sign-in was attempted.",
        stop_reason="",
        last_attempt_reason=None,
        error=None,
        warnings=[],
        last_attempt_at=None,
        finished_at="2026-10-04T12:00:00Z",
    )

    values, _ = asyncio.run(autopilot._resolve_discovery_input_values(None, None, record, setup, discovery))

    assert (values.get("__auth_approved") == "1") is expected_auth_approval
    if expected_auth_approval:
        assert values["__username"] == "saved-user@example.test"
        assert values["__password"] == "saved-secret"
    else:
        assert "runtime_user" not in values
        assert "__username" not in values
        assert "__password" not in values
