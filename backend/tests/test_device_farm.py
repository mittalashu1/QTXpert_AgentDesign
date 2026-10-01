from types import SimpleNamespace

from app.config import Settings
from app.services.device_farm import DeviceFarmError, DeviceFarmService, choose_device


def test_device_farm_is_disabled_without_explicit_project_configuration():
    settings = Settings()
    assert settings.device_farm_configured is False
    assert DeviceFarmService(settings).configured is False


def test_device_selection_prefers_configured_android_device_and_version():
    devices = [
        {
            "arn": "arn:pixel-7",
            "name": "Google Pixel 7",
            "model": "Pixel 7",
            "os": "14",
            "availability": "AVAILABLE",
        },
        {
            "arn": "arn:pixel-8",
            "name": "Google Pixel 8",
            "model": "Pixel 8",
            "os": "14",
            "availability": "AVAILABLE",
        },
    ]

    selected = choose_device(
        devices,
        preferred_arn=None,
        preferred_name="Google Pixel 8",
        platform_version="14",
    )

    assert selected.arn == "arn:pixel-8"


def test_device_selection_reports_missing_device():
    try:
        choose_device([], preferred_arn=None, preferred_name="Google Pixel 8", platform_version="14")
    except DeviceFarmError as exc:
        assert "no Android devices" in str(exc)
    else:  # pragma: no cover - assertion documents the provider contract
        raise AssertionError("empty Device Farm inventory should be actionable")


def test_device_farm_configuration_is_explicit_and_metered():
    settings = Settings(
        DEVICE_FARM_ENABLED=True,
        DEVICE_FARM_PROJECT_ARN="arn:aws:devicefarm:us-west-2:123:project:test",
    )
    assert settings.device_farm_configured is True
    assert settings.DEVICE_FARM_REGION == "us-west-2"
    assert settings.DEVICE_FARM_BILLING_METHOD == "METERED"


def test_running_session_is_accepted_only_when_selected_upload_is_attached():
    app_arn = "arn:aws:devicefarm:us-west-2:123:upload:selected-build"
    device = choose_device(
        [{"arn": "arn:pixel", "name": "Google Pixel 8", "availability": "AVAILABLE"}],
        preferred_arn=None,
        preferred_name="Google Pixel 8",
        platform_version=None,
    )
    service = DeviceFarmService(SimpleNamespace(DEVICE_FARM_SESSION_TIMEOUT_SECONDS=1, DEVICE_FARM_POLL_INTERVAL_SECONDS=1))
    client = SimpleNamespace(get_remote_access_session=lambda **_: {
        "remoteAccessSession": {
            "status": "RUNNING",
            "appUpload": app_arn,
            "endpoints": {"remoteDriverEndpoint": "https://devicefarm.example/session"},
        }
    })

    session = service._wait_for_session(client, "arn:session", app_arn, device)

    assert session.app_attachment_verified is True
    assert session.attached_app_arn == app_arn


def test_running_session_with_another_upload_is_rejected():
    app_arn = "arn:aws:devicefarm:us-west-2:123:upload:selected-build"
    device = choose_device(
        [{"arn": "arn:pixel", "name": "Google Pixel 8", "availability": "AVAILABLE"}],
        preferred_arn=None,
        preferred_name="Google Pixel 8",
        platform_version=None,
    )
    service = DeviceFarmService(SimpleNamespace(DEVICE_FARM_SESSION_TIMEOUT_SECONDS=1, DEVICE_FARM_POLL_INTERVAL_SECONDS=1))
    client = SimpleNamespace(get_remote_access_session=lambda **_: {
        "remoteAccessSession": {
            "status": "RUNNING",
            "appUpload": "arn:aws:devicefarm:us-west-2:123:upload:other-build",
            "endpoints": {"remoteDriverEndpoint": "https://devicefarm.example/session"},
        }
    })

    try:
        service._wait_for_session(client, "arn:session", app_arn, device)
    except DeviceFarmError as exc:
        assert "different app upload" in str(exc)
    else:  # pragma: no cover - assertion documents the attachment contract
        raise AssertionError("a session attached to another app must not be accepted")


def test_session_without_upload_confirmation_times_out_instead_of_assuming_attachment():
    app_arn = "arn:aws:devicefarm:us-west-2:123:upload:selected-build"
    device = choose_device(
        [{"arn": "arn:pixel", "name": "Google Pixel 8", "availability": "AVAILABLE"}],
        preferred_arn=None,
        preferred_name="Google Pixel 8",
        platform_version=None,
    )
    service = DeviceFarmService(SimpleNamespace(DEVICE_FARM_SESSION_TIMEOUT_SECONDS=0, DEVICE_FARM_POLL_INTERVAL_SECONDS=0))
    client = SimpleNamespace(get_remote_access_session=lambda **_: {
        "remoteAccessSession": {
            "status": "RUNNING",
            "endpoints": {"remoteDriverEndpoint": "https://devicefarm.example/session"},
        }
    })

    try:
        service._wait_for_session(client, "arn:session", app_arn, device)
    except DeviceFarmError as exc:
        assert "verified the selected app upload" in str(exc)
    else:  # pragma: no cover - assertion documents the attachment contract
        raise AssertionError("a session without an app upload must not be accepted")

