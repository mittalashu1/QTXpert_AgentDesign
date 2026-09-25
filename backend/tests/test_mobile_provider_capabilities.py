from types import SimpleNamespace

import pytest
from appium import webdriver

from app.schemas.autopilot import (
    AutopilotDiscoveryResult,
    AutopilotDiscoveryRequest,
    AutopilotExecutionRequest,
    AutopilotSuiteRequest,
)
from app.services.autopilot import AutopilotPrototypeService
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_suite import AutopilotSuiteService


@pytest.mark.parametrize("flow", ["smoke", "discovery", "suite"])
@pytest.mark.parametrize(
    ("provider", "app_reference"),
    [
        ("devicefarm", "arn:aws:devicefarm:us-west-2:123456789012:upload:project/app"),
        ("browserstack", "bs://uploaded-app"),
        ("appium", "/test/apps/demo.apk"),
    ],
)
def test_mobile_flows_use_the_provider_app_install_contract(
    tmp_path, monkeypatch, flow, provider, app_reference
):
    """Inspect the actual SDK request at the remote-session boundary, without a paid device."""
    captured = {}

    class SessionCaptured(Exception):
        pass

    def capture_session(url, *, options):
        captured.update(options.to_capabilities())
        raise SessionCaptured()

    monkeypatch.setattr(webdriver, "Remote", capture_session)
    prototype = SimpleNamespace(_job_dir=lambda _job_id: tmp_path)
    settings = SimpleNamespace()
    endpoint = "https://appium.example.test/wd/hub"
    common = dict(provider=provider, device_name="Google Pixel 8", platform_version="14.0")

    with pytest.raises(SessionCaptured):
        if flow == "smoke":
            AutopilotPrototypeService._execute_appium_sync(
                endpoint,
                app_reference,
                AutopilotExecutionRequest(**common),
                tmp_path / "launch.png",
                tmp_path / "source.xml",
                expected_package="com.qtx.demo",
            )
        elif flow == "discovery":
            AutopilotDiscoveryService(settings, prototype)._run_sync(
                "job-provider-contract", endpoint, app_reference,
                AutopilotDiscoveryRequest(**common), "com.qtx.demo", ".MainActivity",
                None, 30_000, 30_000, 30_000,
            )
        else:
            AutopilotSuiteService(settings, prototype)._run_sync(
                "job-provider-contract", endpoint, app_reference,
                AutopilotSuiteRequest(**common), [], "com.qtx.demo",
                None, 30_000, 30_000, 30_000,
                discovery=AutopilotDiscoveryResult(
                    job_id="job-provider-contract",
                    status="completed",
                    provider=provider,
                    started_at="2026-09-25T00:00:00Z",
                    finished_at="2026-09-25T00:00:01Z",
                    duration_seconds=1,
                    device_name="Google Pixel 8",
                    target_activity="com.qtx.demo.MainActivity",
                ),
            )

    assert captured["platformName"] == "Android"
    assert captured["appium:automationName"] == "UiAutomator2"
    if provider == "devicefarm":
        # AWS already installs the APK when creating its remote-access session.
        # An upload ARN is not a supported appium:app URL or filesystem path.
        assert "appium:app" not in captured
        assert "appium:platformVersion" not in captured
    else:
        assert captured["appium:app"] == app_reference
        assert captured["appium:platformVersion"] == "14.0"
    if flow != "smoke":
        assert captured["appium:appPackage"] == "com.qtx.demo"
    if flow == "suite":
        assert captured["appium:appActivity"] == "com.qtx.demo.MainActivity"
