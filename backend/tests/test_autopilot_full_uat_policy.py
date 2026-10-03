from app.config import Settings
from app.schemas.autopilot import DiscoveredControl, DiscoveryLocator
from app.services.autopilot_discovery import AutopilotDiscoveryService
from app.services.autopilot_ir import AutopilotIRCompiler


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
