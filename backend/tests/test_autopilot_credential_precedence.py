import asyncio
import json
from types import SimpleNamespace

from app.api.routes import autopilot


def test_corrected_runtime_credential_takes_precedence_over_old_bundle(monkeypatch):
    async def resolve(*args):
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
    )
    record = SimpleNamespace(surface_key="fh-money", job_id="job", owner_id="owner", project_id="project")
    values, sensitive = asyncio.run(autopilot._resolve_discovery_input_values(None, None, record, setup))

    assert values["runtime_user"] == "corrected-user@example.test"
    assert values["__username"] == "corrected-user@example.test"
    assert values["__password"] == "synthetic-secret"
    assert "runtime_user" in sensitive
    assert "credential_reference" not in values


def test_disabled_sign_in_can_resume_after_corrected_input():
    discovery = SimpleNamespace(status="partial", stop_reason="The observed sign-in button did not become enabled")
    setup = SimpleNamespace(safe_authentication_approved=True)
    assert autopilot._resume_should_run_discovery(False, discovery, setup)
