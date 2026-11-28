from app.config import Settings
from app.schemas.autopilot import AutopilotDiscoveryResult, AutopilotResumeRequest, AutopilotSetupProfile, AutopilotSuiteRequest, DiscoveredControl, DiscoveryLocator
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_ir import AutopilotIRCompiler
from app.services.autopilot_suite import AutopilotSuiteService


def _control(label: str, *, risk: str = "review") -> DiscoveredControl:
    return DiscoveredControl(
        control_id="control-1",
        semantic_label=label,
        clickable=True,
        enabled=True,
        input_capable=False,
        risk=risk,
        locators=[DiscoveryLocator(strategy="accessibility_id", value=label, confidence=0.99)],
    )


def test_full_uat_is_fail_closed_by_default_and_requires_exact_verified_target():
    settings = Settings(
        AUTOPILOT_FULL_UAT_SANDBOX_VERIFIED=False,
        AUTOPILOT_FULL_UAT_TARGET_ALLOWLIST="android:com.fhc.investnation.uat",
    )
    assert not settings.full_uat_target_is_allowed(
        "android",
        "com.fhc.InvestNation.uat",
        "com.fhc.InvestNation.uat",
    )


def test_full_uat_requires_target_identity_match_and_exact_allowlist():
    settings = Settings(
        AUTOPILOT_FULL_UAT_SANDBOX_VERIFIED=True,
        AUTOPILOT_FULL_UAT_TARGET_ALLOWLIST="android:com.fhc.investnation.uat",
    )
    assert settings.full_uat_target_is_allowed(
        "android",
        "com.fhc.InvestNation.uat",
        "com.fhc.InvestNation.uat",
    )
    assert not settings.full_uat_target_is_allowed(
        "android",
        "com.fhc.other.uat",
        "com.fhc.InvestNation.uat",
    )
    assert not settings.full_uat_target_is_allowed(
        "web",
        "com.fhc.InvestNation.uat",
        "com.fhc.InvestNation.uat",
    )


def test_normal_regression_and_smoke_defaults():
    assert AutopilotSetupProfile(job_id="job").preferred_execution_mode == "functional"
    assert AutopilotSuiteRequest().execution_mode == "functional"
    assert AutopilotResumeRequest().auto_run_safe_suite is False


def test_functional_execution_enables_uat_only_for_the_verified_app():
    stamp = "2026-11-28T00:00:00Z"
    discovery = AutopilotDiscoveryResult(
        job_id="job",
        status="completed",
        target_kind="android",
        provider="local_runner",
        device_name="usb-test",
        started_at=stamp,
        finished_at=stamp,
        duration_seconds=0,
        target_ready=True,
        target_identity="com.example.sandbox",
        stop_reason="completed",
    )
    for verified in (False, True):
        settings = Settings(
            AUTOPILOT_FULL_UAT_SANDBOX_VERIFIED=verified,
            AUTOPILOT_FULL_UAT_TARGET_ALLOWLIST="android:com.example.sandbox",
        )
        service = AutopilotSuiteService(settings, None)
        for provider in ("local_runner", "browserstack"):
            batch = AutopilotSuiteRequest(provider=provider, run_all_eligible=True)
            assert service._verified_uat_enabled(batch, discovery, "com.example.sandbox") is verified
            assert not service._verified_uat_enabled(batch, discovery, "com.example.other")
            assert not service._verified_uat_enabled(batch, discovery.model_copy(update={"target_ready": False}), "com.example.sandbox")
            legacy = AutopilotSuiteRequest(provider=provider)
            assert not service._verified_uat_enabled(legacy, discovery, "com.example.sandbox")
            smoke = AutopilotSuiteRequest(provider=provider, execution_mode="safe_navigation")
            assert not service._verified_uat_enabled(smoke, discovery, "com.example.sandbox")


def test_transaction_module_entry_is_map_only_and_needs_explicit_discovery_choice():
    risk, _ = AutopilotDiscoveryService._risk("Transfers", {})
    assert risk == "review"
    submit_risk, _ = AutopilotDiscoveryService._risk("Submit transfer", {})
    assert submit_risk == "blocked"

    transfer = _control("Transfers")
    assert AutopilotDiscoveryService._select_safe_control([transfer], set()) is None
    assert AutopilotDiscoveryService._select_safe_control(
        [transfer], set(), include_transaction_journeys=True
    ) == transfer


def test_transaction_discovery_does_not_advance_forms_and_full_uat_keeps_otp_blocked():
    assert AutopilotDiscoveryService._is_transaction_progress_control("Continue")
    assert not AutopilotDiscoveryService._is_transaction_progress_control("Accounts")

    transfer_submit = _control("Submit transfer", risk="blocked")
    otp_submit = _control("Confirm OTP", risk="blocked")
    delete_account = _control("Delete account", risk="blocked")
    assert AutopilotIRCompiler._full_uat_control_allowed(transfer_submit)
    assert not AutopilotIRCompiler._full_uat_control_allowed(otp_submit)
    assert not AutopilotIRCompiler._full_uat_control_allowed(delete_account)
