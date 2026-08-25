from pathlib import Path

from app.config import Settings
from app.services.autopilot import AutopilotPrototypeService


def _service(tmp_path: Path, **overrides) -> AutopilotPrototypeService:
    settings = Settings(AUTOPILOT_STORAGE_PATH=str(tmp_path), **overrides)
    return AutopilotPrototypeService(settings)


def test_autopilot_generates_core_and_permission_tests(tmp_path):
    service = _service(tmp_path)
    meta = {
        "permissions": [
            "android.permission.INTERNET",
            "android.permission.CAMERA",
            "android.permission.POST_NOTIFICATIONS",
        ],
        "debuggable": False,
    }

    tests = service._build_deterministic_tests(meta)
    titles = {test.title for test in tests}

    assert "Install and cold-launch application" in titles
    assert "Network loss and recovery behavior" in titles
    assert "Camera permission grant and denial" in titles
    assert "Notifications permission grant and denial" in titles
    assert all(test.destructive is False for test in tests)


def test_autopilot_flags_debuggable_build(tmp_path):
    service = _service(tmp_path)
    tests = service._build_deterministic_tests({"permissions": [], "debuggable": True})

    assert any(test.id == "QT-AUTO-SEC-DEBUG" for test in tests)
    risks = service._fallback_risks({"permissions": [], "debuggable": True})
    assert any("debuggable" in risk.lower() for risk in risks)


def test_autopilot_infers_financial_domain_from_context(tmp_path):
    service = _service(tmp_path)
    domain = service._infer_domain(
        {"app_name": "Customer App", "package_name": "com.example.mobile"},
        "UAT retail banking application with payment and investment journeys",
    )

    assert domain == "Banking / Financial Services"


def test_autopilot_questions_remain_guardrail_focused(tmp_path):
    service = _service(tmp_path)
    questions = service._fallback_questions({"permissions": ["android.permission.INTERNET"]})

    assert len(questions) <= 6
    joined = " ".join(questions).lower()
    assert "credentials" in joined
    assert "prohibited" in joined
    assert "external" in joined


def test_appium_connection_errors_are_blocked_not_product_failures():
    exc = RuntimeError("HTTPConnectionPool: connection refused")
    assert AutopilotPrototypeService._looks_like_connector_problem(exc) is True


def test_missing_browserstack_configuration_is_blocked_not_product_failure():
    exc = RuntimeError(
        "BrowserStack is not configured. Set BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY as backend secrets."
    )
    assert AutopilotPrototypeService._looks_like_connector_problem(exc) is True


def test_browserstack_configuration_requires_both_secrets(tmp_path):
    incomplete = _service(tmp_path, BROWSERSTACK_USERNAME="user")
    configured = _service(
        tmp_path,
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
    )

    assert incomplete.settings.browserstack_configured is False
    assert configured.settings.browserstack_configured is True


def test_capabilities_follow_manifest_permissions(tmp_path):
    service = _service(tmp_path)
    capabilities = service._capabilities(
        {
            "permissions": [
                "android.permission.INTERNET",
                "android.permission.ACCESS_FINE_LOCATION",
            ]
        }
    )

    assert capabilities["static_apk_analysis"] is True
    assert capabilities["appium_smoke_execution"] is True
    assert capabilities["network_test_candidate"] is True
    assert capabilities["location_test_candidate"] is True
    assert capabilities["camera_test_candidate"] is False
