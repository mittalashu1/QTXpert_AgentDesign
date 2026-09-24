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
