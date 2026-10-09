import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    AutopilotSuiteRequest,
    DiscoveryLocator,
    RuntimePromptChoice,
    RuntimePromptObservation,
)
from app.api.routes import autopilot as autopilot_routes


def _observed_permission_prompt():
    return RuntimePromptObservation(
        prompt_id="runtime-permission-1",
        kind="runtime_permission",
        title="Android permission prompt",
        choices=[
            RuntimePromptChoice(
                key="allow",
                label="Allow",
                decision="allow",
                locators=[DiscoveryLocator(strategy="id", value="permission_allow", confidence=0.97)],
            )
        ],
    )


def _stalled_discovery(job_id):
    return AutopilotDiscoveryResult(
        job_id=job_id,
        status="partial",
        target_kind="android",
        provider="devicefarm",
        started_at="2026-10-01T00:00:00+00:00",
        finished_at="2026-10-01T00:00:10+00:00",
        duration_seconds=10,
        device_name="Pixel",
        target_ready=True,
        interactive_surface_ready=False,
        runtime_prompts=[_observed_permission_prompt()],
    )


def test_prompt_only_discovery_gate_requires_verified_target_and_replayable_choice():
    partial = _stalled_discovery("prompt-job")

    assert autopilot_routes._discovery_supports_prompt_only_execution(partial) is True
    assert autopilot_routes._discovery_supports_prompt_only_execution(
        partial.model_copy(update={"target_ready": False})
    ) is False
    assert autopilot_routes._discovery_supports_prompt_only_execution(
        partial.model_copy(update={"runtime_prompts": []})
    ) is False
    assert autopilot_routes._discovery_supports_prompt_only_execution(
        partial.model_copy(update={"last_attempt_status": "blocked"})
    ) is False


@pytest.mark.asyncio
async def test_safe_suite_endpoint_allows_verified_prompt_only_checkpoint(monkeypatch):
    job_id = "88888888-8888-4888-8888-888888888888"
    discovery = _stalled_discovery(job_id)
    job = {"job_id": job_id, "phase": "partial", "target_kind": "android"}

    class FakeService:
        pass

    class GatePassed(RuntimeError):
        pass

    async def require_owned_job(_service, _job_id, _user, **_kwargs):
        return job

    async def stop_after_discovery_gate(*_args, **_kwargs):
        raise GatePassed()

    monkeypatch.setattr(autopilot_routes, "_service", lambda _settings: FakeService())
    monkeypatch.setattr(autopilot_routes, "_require_owned_job", require_owned_job)
    monkeypatch.setattr(
        autopilot_routes,
        "_safe_job_record",
        lambda *_args, **_kwargs: asyncio.sleep(
            0, result=SimpleNamespace(discovery=discovery.model_dump(mode="json"))
        ),
    )
    monkeypatch.setattr(
        autopilot_routes, "_advance_suite_job_to_running", stop_after_discovery_gate
    )

    with pytest.raises(GatePassed):
        await autopilot_routes.execute_autopilot_suite(
            job_id,
            AutopilotSuiteRequest(
                provider="devicefarm",
                device_name="Pixel",
                prompt_only=True,
            ),
            SimpleNamespace(id="owner"),
            Settings(),
            None,
        )
