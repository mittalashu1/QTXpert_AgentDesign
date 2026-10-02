import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.device_farm import DeviceFarmError, DeviceFarmService, DeviceFarmTrialBalanceError


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
    with pytest.raises(DeviceFarmTrialBalanceError, match="missing_balance"):
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


def test_provider_status_does_not_check_trial_balance_until_requested(monkeypatch):
    from app.api.routes.autopilot import get_autopilot_providers

    calls = []
    def forbidden_balance_check(_):
        calls.append("called")
        raise AssertionError("Provider status must not read AWS trial minutes.")

    monkeypatch.setattr(DeviceFarmService, "get_trial_minutes", forbidden_balance_check)
    settings = Settings(DEVICE_FARM_ENABLED=True, DEVICE_FARM_PROJECT_ARN="arn:aws:devicefarm:us-west-2:123:project:test")
    result = asyncio.run(get_autopilot_providers(SimpleNamespace(), settings))

    assert calls == []
    assert result.device_farm_trial_minutes_remaining is None
    assert result.device_farm_trial_minutes_checked_at is None
    assert result.device_farm_trial_minutes_error is None


@pytest.mark.parametrize("sdk_code, expected", [
    ("AccessDeniedException", "access_denied"),
    ("ExpiredTokenException", "expired_credentials"),
    ("synthetic-secret", "unknown"),
])
def test_trial_failure_keeps_only_an_allowlisted_reason(monkeypatch, sdk_code, expected):
    service = DeviceFarmService(Settings())
    class SDKError(Exception):
        response = {"Error": {"Code": sdk_code, "Message": "synthetic-secret"}}
    def fail():
        raise SDKError("synthetic-secret")
    monkeypatch.setattr(service, "_client", lambda: SimpleNamespace(get_account_settings=fail))
    with pytest.raises(DeviceFarmTrialBalanceError) as exc:
        service.get_trial_minutes()
    assert exc.value.code == expected
    assert "synthetic-secret" not in str(exc.value)
