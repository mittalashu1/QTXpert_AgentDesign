import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.device_farm import DeviceFarmError, DeviceFarmService


@pytest.mark.parametrize("remaining", [0, 938, 937.5])
def test_trial_minutes_reads_only_actual_sdk_balance(monkeypatch, remaining):
    service = DeviceFarmService(Settings())
    calls = []
    class Client:
        def get_account_settings(self):
            calls.append("read")
            return {"accountSettings": {"trialMinutes": {"total": 1000, "remaining": remaining}}}
    monkeypatch.setattr(service, "_client", lambda: Client())
    result = service.get_trial_minutes()
    assert result["remaining"] == remaining
    assert result["total"] == 1000
    assert result["checked_at"]
    assert calls == ["read"]


@pytest.mark.parametrize("remaining", [None, -1, "938", True, float("nan"), float("inf")])
def test_unknown_balance_is_never_an_assumed_trial(monkeypatch, remaining):
    service = DeviceFarmService(Settings())
    client = SimpleNamespace(get_account_settings=lambda: {"accountSettings": {"trialMinutes": {"remaining": remaining}}})
    monkeypatch.setattr(service, "_client", lambda: client)
    with pytest.raises(DeviceFarmError, match="verified remaining"):
        service.get_trial_minutes()


@pytest.mark.parametrize("error_type", [RuntimeError, DeviceFarmError])
def test_trial_minutes_does_not_echo_provider_secrets(monkeypatch, error_type):
    service = DeviceFarmService(Settings())
    def fail():
        raise error_type("password=synthetic-secret token=synthetic-token")
    monkeypatch.setattr(service, "_client", lambda: SimpleNamespace(get_account_settings=fail))
    with pytest.raises(DeviceFarmError) as exc:
        service.get_trial_minutes()
    assert "synthetic" not in str(exc.value)


def test_authenticated_provider_status_exposes_timestamped_read_only_balance(monkeypatch):
    from app.api.routes.autopilot import get_autopilot_providers
    monkeypatch.setattr(DeviceFarmService, "get_trial_minutes", lambda _: {
        "remaining": 916.5, "total": 1000, "checked_at": "2026-09-27T15:30:00+00:00",
    })
    settings = Settings(DEVICE_FARM_ENABLED=True, DEVICE_FARM_PROJECT_ARN="arn:aws:devicefarm:us-west-2:123:project:test")
    result = asyncio.run(get_autopilot_providers(SimpleNamespace(), settings))
    assert result.device_farm_trial_minutes_remaining == 916.5
    assert result.device_farm_trial_minutes_checked_at == "2026-09-27T15:30:00+00:00"


def test_provider_status_does_not_expose_error_payload_or_assume_zero(monkeypatch):
    from app.api.routes.autopilot import get_autopilot_providers
    def fail(_):
        raise RuntimeError("synthetic-secret")
    monkeypatch.setattr(DeviceFarmService, "get_trial_minutes", fail)
    settings = Settings(DEVICE_FARM_ENABLED=True, DEVICE_FARM_PROJECT_ARN="arn:aws:devicefarm:us-west-2:123:project:test")
    result = asyncio.run(get_autopilot_providers(SimpleNamespace(), settings))
    assert result.device_farm_trial_minutes_remaining is None
    assert "synthetic-secret" not in result.device_farm_trial_minutes_error
