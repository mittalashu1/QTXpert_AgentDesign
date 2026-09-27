import asyncio
import json
from types import SimpleNamespace

import pytest

from app.api.routes import autopilot


@pytest.mark.parametrize("field_time,bundle_time,expected", [
    (None, None, "corrected-user@example.test"),
    ("2026-09-27T11:00:00Z", "2026-09-27T10:00:00Z", "corrected-user@example.test"),
    ("2026-09-27T10:00:00Z", "2026-09-27T11:00:00Z", "old-user@example.test"),
])
def test_corrected_runtime_credential_takes_precedence_over_old_bundle(monkeypatch, field_time, bundle_time, expected):
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
