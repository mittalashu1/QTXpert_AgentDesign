import json
import os
import struct
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.config import Settings
from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotDiscoveryResult,
    AutopilotExecutionRequest,
    AutopilotInputRequest,
    AutopilotSavedInput,
    AutopilotSetupProfile,
    AutopilotSuiteResult,
    AutopilotSuiteTestResult,
    AutopilotTest,
    DiscoveredControl,
    DiscoveredScreen,
    DiscoveredTransition,
    DiscoveryLocator,
)
from app.api.routes.autopilot import (
    _autopilot_safe_case_metadata,
    _blocking_checkpoint_requests,
    _effective_context,
    _merge_discovery_snapshot,
    _pending_runtime_auth_requests,
    _refresh_mobile_analysis_identity,
    _remove_local_report_data,
    _sanitize_discovery_assets,
    _setup_profile,
    _strip_suite_evidence_paths,
)
from app.api.routes.executions import _validate_autopilot_case_scope
from app.services.autopilot import (
    AutopilotPrototypeService,
    AutopilotUploadTooLarge,
    build_report_tab_key,
    build_surface_key,
    normalize_surface_identity,
)
from app.services.autopilot_ir import AutopilotIRCompiler, credential_value_available
from app.services.autopilot_context import (
    DEFAULT_AUTOPILOT_CONTEXT,
    DEFAULT_AUTOPILOT_PROFILE_ID,
    list_profiles,
    profile_context,
)
from app.services.autopilot_report import build_test_audit_report


def _service(tmp_path: Path, **overrides) -> AutopilotPrototypeService:
    settings = Settings(AUTOPILOT_STORAGE_PATH=str(tmp_path), **overrides)
    return AutopilotPrototypeService(settings)


def test_autopilot_case_metadata_and_execution_gate_keep_one_surface():
    test = AutopilotTest(
        id="QT-AUTO-FUNCTIONAL-001",
        suite="Functional",
        title="Open the public landing screen",
        objective="Validate the observed entry point",
    )
    metadata = _autopilot_safe_case_metadata(
        test,
        "job-investnation",
        scope={
            "autopilot_surface_key": "surface-investnation-android",
            "autopilot_surface_identity": "sha256:" + "a" * 64,
            "autopilot_profile_id": "uae_fintech",
            "autopilot_target_kind": "android",
            "autopilot_repository_asset_id": "11111111-1111-4111-8111-111111111111",
        },
    )
    assert metadata["autopilot_surface_key"] == "surface-investnation-android"
    assert metadata["autopilot_target_kind"] == "android"

    first = SimpleNamespace(test_data=metadata)
    second = SimpleNamespace(test_data={**metadata, "autopilot_surface_key": "surface-other-build"})
    with pytest.raises(Exception, match="different profiles"):
        _validate_autopilot_case_scope(
            [first, second],
            target_kind="android",
            app_asset_id=None,
        )


def test_initial_checkpoint_is_target_driven_and_does_not_show_plan_references():
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-1111-1111-111111111111",
        filename="investnation.apk",
        sha256="a" * 64,
        checkpoint_stage="input_collection",
        tests=[AutopilotTest(
            id="QT-AUTO-UAT-001",
            suite="UAT",
            title="Authenticated customer journey",
            objective="Validate the customer journey",
            requires_auth=True,
            requires_test_data=True,
            bucket="uat",
        )],
    )
    setup = _setup_profile(
        analysis.job_id,
        {"account_role": "UAT investor", "acceptance_criteria_reference": "qtxpert://criteria/uat"},
        analysis,
        discovery=None,
    )
    assert setup.input_requests == []
    assert setup.runtime_input_requests == []
    assert setup.checkpoint_stage == "runtime_discovery"


def test_speculative_auth_plan_does_not_prompt_on_public_discovery():
    analysis = AutopilotAnalysis(
        job_id="12121212-1212-1212-1212-121212121212",
        filename="public.apk",
        sha256="d" * 64,
        tests=[AutopilotTest(
            id="QT-AUTO-UAT-002",
            suite="UAT",
            title="Authenticated customer journey",
            objective="Validate a contextual journey",
            requires_auth=True,
            bucket="uat",
        )],
    )
    public_control = DiscoveredControl(
        control_id="help",
        semantic_label="Help",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/help", confidence=0.99)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-13T00:00:00+00:00",
        finished_at="2026-09-13T00:00:01+00:00",
        duration_seconds=1,
        device_name="test",
        screens=[DiscoveredScreen(screen_id="home", fingerprint="f" * 64, controls=[public_control])],
    )

    setup = _setup_profile(analysis.job_id, {}, analysis, discovery)

    assert not any(item.key in {"credential_reference", "safe_authentication_approved"} for item in setup.input_requests)
    assert _blocking_checkpoint_requests(setup) == []
    assert setup.checkpoint_stage == "ready"


def test_account_role_is_not_a_blocking_authentication_checkpoint():
    role = AutopilotInputRequest(
        key="account_role",
        label="Test account role",
        category="credential",
        reason="Optional role metadata",
    )
    credential = role.model_copy(update={"key": "credential_reference", "label": "UAT sign-in credentials", "sensitive": True})
    setup = AutopilotSetupProfile(job_id="22222222-2222-2222-2222-222222222222", input_requests=[role, credential])
    assert [item.key for item in _blocking_checkpoint_requests(setup)] == ["credential_reference"]
    assert [item.key for item in _pending_runtime_auth_requests(setup)] == ["credential_reference"]


def test_stale_provided_decision_cannot_hide_missing_credential_value():
    analysis = AutopilotAnalysis(
        job_id="33333333-3333-3333-3333-333333333333",
        filename="investnation.apk",
        sha256="b" * 64,
        tests=[AutopilotTest(
            id="QT-AUTO-AUTH-001",
            suite="Functional",
            title="Authenticate customer",
            objective="Validate sign-in",
            requires_auth=True,
        )],
    )
    setup = _setup_profile(
        analysis.job_id,
        {"input_decisions": {"credential_reference": "provide"}},
        analysis,
        discovery=AutopilotDiscoveryResult(
            job_id=analysis.job_id,
            status="completed",
            provider="appium",
            started_at="2026-09-13T00:00:00+00:00",
            finished_at="2026-09-13T00:00:01+00:00",
                duration_seconds=1,
                device_name="test",
                screens=[DiscoveredScreen(
                    screen_id="login",
                    fingerprint="g" * 64,
                    controls=[DiscoveredControl(
                        control_id="username",
                        semantic_label="User ID / email",
                        class_name="android.widget.EditText",
                        input_capable=True,
                        input_kind="credential",
                        locators=[DiscoveryLocator(strategy="id", value="com.example:id/username", confidence=0.99)],
                    )],
                )],
            ),
        )
    credential = next(item for item in setup.input_requests if item.key == "credential_reference")
    assert credential.status == "pending"
    assert credential.reference_present is False
    # The credential bundle is the single live checkpoint shown to the user;
    # the safe-authentication approval is rendered alongside it as a switch.
    assert [item.key for item in _blocking_checkpoint_requests(setup)] == ["credential_reference"]


def test_runtime_login_checkpoint_keeps_observed_screen_metadata_on_bundle():
    """A live login must open the exact screen, not the generic setup form."""
    analysis = AutopilotAnalysis(
        job_id="34343434-3434-3434-3434-343434343434",
        filename="investnation.apk",
        sha256="e" * 64,
        tests=[AutopilotTest(
            id="QT-AUTO-AUTH-OBSERVED",
            suite="UAT",
            title="Sign in and reach the dashboard",
            objective="Validate the observed sign-in entry point.",
            requires_auth=True,
            bucket="uat",
        )],
    )
    username = DiscoveredControl(
        control_id="username",
        semantic_label="User ID / email",
        class_name="android.widget.EditText",
        input_capable=True,
        input_kind="credential",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/user", confidence=0.99)],
    )
    password = DiscoveredControl(
        control_id="password",
        semantic_label="Password",
        class_name="android.widget.EditText",
        input_capable=True,
        input_kind="credential",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/password", confidence=0.99)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="partial",
        provider="appium",
        started_at="2026-09-13T00:00:00+00:00",
        finished_at="2026-09-13T00:00:01+00:00",
        duration_seconds=1,
        device_name="test",
        screens=[DiscoveredScreen(
            screen_id="login-screen",
            fingerprint="h" * 64,
            journey="Account access",
            page_label="Sign in",
            controls=[username, password],
        )],
    )

    setup = _setup_profile(analysis.job_id, {}, analysis, discovery)
    bundle = next(item for item in setup.input_requests if item.key == "credential_reference")

    assert bundle.source == "runtime"
    assert bundle.screen_id == "login-screen"
    assert bundle.page_label == "Sign in"
    assert bundle.field_label == "User ID / email + Password"
    assert "QT-AUTO-AUTH-OBSERVED" in bundle.required_for


def test_persisted_runtime_checkpoint_is_reopened_when_value_metadata_is_missing():
    analysis = AutopilotAnalysis(
        job_id="44444444-4444-4444-4444-444444444444",
        filename="investnation.apk",
        sha256="c" * 64,
        tests=[],
    )
    runtime_request = AutopilotInputRequest(
        key="runtime_username",
        label="User ID / email",
        category="credential",
        reason="Observed login field",
        source="runtime",
        sensitive=True,
        input_hint="username",
        status="provided",
        reference_present=True,
    )
    setup = _setup_profile(
        analysis.job_id,
        {
            "input_decisions": {"runtime_username": "provide"},
            "runtime_input_requests": [runtime_request.model_dump(mode="json")],
        },
        analysis,
        discovery=None,
    )
    reopened = setup.runtime_input_requests[0]
    assert reopened.status == "pending"
    assert reopened.reference_present is False
    assert [item.key for item in _blocking_checkpoint_requests(setup)] == ["runtime_username"]


def test_context_boundary_redacts_natural_language_secrets():
    safe = _effective_context(
        "Use username as qa@example.test and password as SuperSecret!",
        "general_mobile",
    )
    assert "SuperSecret!" not in safe
    assert "password [REDACTED]" in safe
    assert "qa@example.test" not in safe
    assert "username [REDACTED]" in safe


def test_functional_only_request_filters_nonfunctional_and_installation_cases():
    tests = [
        AutopilotTest(id="FUNC", suite="Functional", bucket="functional_positive", title="Open profile", objective="Observed safe journey."),
        AutopilotTest(id="PAGE", suite="Page-level", bucket="page_level", title="Inspect profile", objective="Observed screen."),
        AutopilotTest(id="UAT", suite="UAT · Positive", bucket="uat", title="Reach observed profile", objective="Observed functional acceptance journey."),
        AutopilotTest(id="UI", suite="UI", bucket="ui", title="Visual profile layout", objective="Visual baseline."),
        AutopilotTest(id="SEC", suite="Security", bucket="security", title="Package posture", objective="Static check."),
        AutopilotTest(id="INSTALL", suite="Smoke", bucket="installation", title="Install app", objective="Launch check."),
    ]

    selected = AutopilotPrototypeService._filter_tests_for_requested_scope(
        tests,
        "Create all functional test cases for the modules listed below.",
    )

    assert {item.bucket for item in selected} == {"functional_positive", "page_level", "uat"}


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
    assert {
        "installation",
        "page_level",
        "functional_positive",
        "functional_negative",
        "ui",
        "accessibility",
        "ui_positive",
        "ui_negative",
        "performance",
        "security",
        "compatibility",
        "resilience",
        "permissions",
        "regression",
    }.issubset({test.bucket for test in tests})


def test_autopilot_initial_plan_is_safe_and_defers_business_workflows(tmp_path):
    service = _service(tmp_path)
    tests = service._build_deterministic_tests({"permissions": []})

    # The static mobile pass is intentionally limited to evidence-backed
    # platform/read-only baselines.  Business UAT/SIT anchors are added only
    # after Runtime Discovery observes the corresponding controls or service.
    assert len(tests) >= 13
    buckets = {test.bucket for test in tests}
    assert {"functional_positive", "functional_negative", "ui_positive", "ui_negative"}.issubset(buckets)
    assert "uat" not in buckets
    assert "sit" not in buckets
    assert "integration" not in buckets
    assert all(not test.requires_auth and not test.requires_test_data for test in tests)
    assert any(test.suite == "UI · Positive" for test in tests)
    assert any(test.suite == "UI · Negative" for test in tests)


def test_ios_baseline_uses_ipa_and_ios_device_language(tmp_path):
    service = _service(tmp_path)
    tests = service._build_deterministic_tests({"platform": "ios", "permissions": []})

    smoke = next(test for test in tests if test.id == "QT-AUTO-SMOKE-001")
    compatibility = next(test for test in tests if test.id == "QT-AUTO-COMPAT-001")

    assert smoke.title == "Install and cold-launch iOS application"
    assert "uploaded IPA" in smoke.steps[0]
    assert "iOS device" in smoke.steps[0]
    assert compatibility.dependency == "A signed iOS build is required for iOS coverage."

    capabilities = service._capabilities({"platform": "ios", "permissions": []})
    assert capabilities["static_ipa_analysis"] is True
    assert capabilities["static_apk_analysis"] is False
    assert capabilities["runtime_app_discovery"] is True
    assert capabilities["network_test_candidate"] is True


def test_pending_auth_guard_includes_compact_plan_credential_bundle():
    bundle = AutopilotInputRequest(
        key="credential_reference",
        label="Sign-in · User ID / email + Password",
        category="credential",
        reason="A non-production sign-in is required.",
        credential_bundle=True,
        status="pending",
    )
    setup = AutopilotSetupProfile(
        job_id="11111111-1111-1111-1111-111111111111",
        input_requests=[bundle],
    )

    assert _pending_runtime_auth_requests(setup) == [bundle]


def test_legacy_signin_bundle_label_satisfies_runtime_credentials():
    setup = AutopilotSetupProfile(
        job_id="22222222-2222-2222-2222-222222222222",
        input_decisions={"credential_reference": "provide"},
        saved_inputs=[AutopilotSavedInput(
            key="credential_reference",
            label="Sign-in · User ID / email + Password",
            category="credential",
            decision="provide",
            has_value=True,
            save_for_reuse=True,
            source="runtime",
        )],
        runtime_input_requests=[AutopilotInputRequest(
            key="runtime_username",
            label="Sign-in · Username · User ID / email",
            category="credential",
            reason="Observed sign-in field",
            source="runtime",
            input_hint="username",
            status="pending",
        )],
    )

    assert credential_value_available(setup) is True


def test_generic_credential_reference_label_does_not_satisfy_runtime_credentials():
    setup = AutopilotSetupProfile(
        job_id="33333333-3333-3333-3333-333333333333",
        input_decisions={"credential_reference": "provide"},
        saved_inputs=[AutopilotSavedInput(
            key="credential_reference",
            label="Credential set reference",
            category="credential",
            decision="provide",
            has_value=True,
            save_for_reuse=True,
            source="plan",
        )],
        runtime_input_requests=[AutopilotInputRequest(
            key="runtime_username",
            label="Sign-in · Username · User ID / email",
            category="credential",
            reason="Observed sign-in field",
            source="runtime",
            input_hint="username",
            status="pending",
        )],
    )

    assert credential_value_available(setup) is False


def test_saved_bundle_clears_pending_runtime_credential_bundle_with_generic_hint():
    analysis = AutopilotAnalysis(
        job_id="44444444-4444-4444-4444-444444444444",
        filename="investnation.apk",
        sha256="b" * 64,
        tests=[AutopilotTest(
            id="QT-AUTO-FUNC-001",
            suite="Functional",
            title="Authenticated journey",
            objective="Validate the authenticated journey",
            requires_auth=True,
            bucket="functional_positive",
        )],
    )
    # Some older Android adapters labelled a credential control simply
    # "Authentication", which yields a generic text hint. The saved bundle
    # must still satisfy the username/password pair; only an explicit OTP
    # request remains a separate gate.
    credential_control = DiscoveredControl(
        control_id="authentication",
        semantic_label="Authentication",
        class_name="android.widget.EditText",
        clickable=False,
        enabled=True,
        input_capable=True,
        input_kind="credential",
        risk="review",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/auth", confidence=0.98)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-15T00:00:00+00:00",
        finished_at="2026-09-15T00:00:01+00:00",
        duration_seconds=1,
        device_name="test",
        screens=[DiscoveredScreen(screen_id="login", fingerprint="c" * 64, controls=[credential_control])],
    )
    setup = _setup_profile(
        analysis.job_id,
        {
            "safe_authentication_approved": True,
            "input_decisions": {
                "credential_reference": "provide",
                "safe_authentication_approved": "provide",
            },
            "saved_inputs": [AutopilotSavedInput(
                key="credential_reference",
                label="UAT sign-in credentials",
                category="credential",
                decision="provide",
                has_value=True,
                save_for_reuse=True,
                source="runtime",
            ).model_dump(mode="json")],
        },
        analysis,
        discovery,
    )

    bundle = next(item for item in setup.input_requests if item.key == "credential_reference")
    assert bundle.status == "provided"
    assert bundle.reference_present is True
    assert _pending_runtime_auth_requests(setup) == []


def test_runtime_discovery_expands_cases_from_observed_controls(tmp_path):
    service = _service(tmp_path)
    baseline = service._build_deterministic_tests({"permissions": []})
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-1111-1111-111111111111",
        filename="investnation.apk",
        sha256="0" * 64,
        tests=baseline,
    )
    sign_in = DiscoveredControl(
        control_id="sign-in",
        semantic_label="Sign in",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/sign_in", confidence=0.98)],
    )
    username = DiscoveredControl(
        control_id="username",
        semantic_label="Username",
        class_name="android.widget.EditText",
        clickable=False,
        enabled=True,
        input_capable=True,
        input_kind="credential",
        risk="review",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/username", confidence=0.98)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=1,
        control_count=2,
        safe_control_count=1,
        screens=[
            DiscoveredScreen(
                screen_id="screen-001",
                fingerprint="a" * 64,
                activity_name=".MainActivity",
                controls=[sign_in, username],
            )
        ],
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)
    buckets = {test.bucket for test in expanded.tests}

    assert len(expanded.tests) > len(baseline)
    # A credential field is a concrete runtime checkpoint, so the deeper UAT
    # and SIT queues become eligible only in this observed branch. The engine
    # must not create a negative credential case from a username-only screen.
    assert {"functional_positive", "uat", "sit"}.issubset(buckets)
    assert not any(
        "username" in test.title.casefold()
        and test.bucket in {"functional_negative", "ui_negative"}
        for test in expanded.tests
    )
    assert any("Sign in" in test.title for test in expanded.tests)
    assert any(test.requires_test_data for test in expanded.tests)
    assert any("Runtime Discovery refreshed" in item for item in expanded.analysis_basis)


def test_runtime_discovery_back_case_targets_unique_observed_predecessor(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="55555555-5555-5555-5555-555555555555",
        filename="navigation.apk",
        sha256="5" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    login = DiscoveredControl(
        control_id="login",
        semantic_label="Login",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/login", confidence=0.98)],
    )
    open_details = DiscoveredControl(
        control_id="open-details",
        semantic_label="Open details",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/details", confidence=0.98)],
    )
    back = DiscoveredControl(
        control_id="back",
        semantic_label="Back",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        risk="safe",
        locators=[DiscoveryLocator(strategy="accessibility_id", value="Back", confidence=0.98)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-25T00:00:00+00:00",
        finished_at="2026-09-25T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screens=[
            DiscoveredScreen(screen_id="screen-001", fingerprint="a" * 64, controls=[login, open_details]),
            DiscoveredScreen(screen_id="screen-002", fingerprint="b" * 64, controls=[back]),
        ],
        transitions=[DiscoveredTransition(
            from_screen_id="screen-001",
            to_screen_id="screen-002",
            control_id="open-details",
            control_label="Open details",
            action="tap",
        )],
    )

    stale_back_case = AutopilotTest(
        id=service._runtime_case_id("FUNC-POS", "screen-002", "back"),
        suite="Functional · Positive",
        bucket="functional_positive",
        title="Observed journey 2 — Functional positive: activate Back on Observed page 2",
        priority="high",
        objective="Old assertion retained from a prior map.",
        steps=["Launch application", "Tap Back", "Verify Back"],
        expected=["Back remains visible"],
    )
    analysis = analysis.model_copy(update={"tests": [*analysis.tests, stale_back_case]})

    expanded = service.expand_discovered_coverage(analysis, discovery)
    back_case = next(test for test in expanded.tests if "activate Back" in test.title)
    compiled = AutopilotIRCompiler().compile_bundle(
        AutopilotAnalysis.model_validate(expanded.model_dump()),
        discovery,
    )
    executable_back = next(test for test in compiled.tests if test.test_id == back_case.id)

    assert back_case.steps[-1] == "Verify Login"
    refreshed_back = next(test for test in expanded.tests if test.id == stale_back_case.id)
    assert refreshed_back.steps[-1] == "Verify Login"
    assert executable_back.readiness == "executable"
    assert any(step.action == "assert_visible" and step.target == "Login" for step in executable_back.steps)
    assert next(step for step in executable_back.steps if step.action == "assert_visible").screen_id == "screen-001"


def test_runtime_discovery_keeps_all_observed_cases_without_fixed_cap(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="44444444-4444-4444-4444-444444444444",
        filename="wide-surface.apk",
        sha256="4" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    screens = []
    for screen_index in range(12):
        controls = []
        for control_index in range(8):
            controls.append(DiscoveredControl(
                control_id=f"safe-{screen_index}-{control_index}",
                semantic_label=f"Open module {screen_index} {control_index}",
                class_name="android.widget.Button",
                clickable=True,
                enabled=True,
                risk="safe",
                locators=[DiscoveryLocator(
                    strategy="id",
                    value=f"com.example:id/{screen_index}_{control_index}",
                    confidence=0.98,
                )],
            ))
        screens.append(DiscoveredScreen(
            screen_id=f"screen-{screen_index}",
            fingerprint=f"{screen_index:064d}",
            activity_name=".MainActivity",
            controls=controls,
        ))
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=len(screens),
        control_count=96,
        safe_control_count=96,
        screens=screens,
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)

    assert len(expanded.tests) > 100
    assert any("Open module 11 7" in test.title for test in expanded.tests)
    assert any("no artificial case-count cap" in item for item in expanded.analysis_basis)


def test_runtime_discovery_does_not_guess_uat_or_sit_for_public_surface(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="33333333-3333-3333-3333-333333333333",
        filename="public.apk",
        sha256="2" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    help_control = DiscoveredControl(
        control_id="help",
        semantic_label="Help",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/help", confidence=0.99)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=1,
        control_count=1,
        safe_control_count=1,
        screens=[DiscoveredScreen(screen_id="home", fingerprint="c" * 64, controls=[help_control])],
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)
    buckets = {test.bucket for test in expanded.tests}

    assert "uat" not in buckets
    assert "sit" not in buckets
    assert not any(test.requires_test_data for test in expanded.tests)


def test_runtime_discovery_does_not_treat_login_link_as_auth_checkpoint(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="44444444-4444-4444-4444-444444444444",
        filename="public.apk",
        sha256="4" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    login_link = DiscoveredControl(
        control_id="login-link",
        semantic_label="Log in",
        class_name="android.widget.TextView",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/login", confidence=0.99)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=1,
        control_count=1,
        safe_control_count=1,
        screens=[DiscoveredScreen(screen_id="home", fingerprint="d" * 64, controls=[login_link])],
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)

    assert not any(test.bucket in {"uat", "sit"} for test in expanded.tests)
    assert not any(test.requires_auth for test in expanded.tests)


def test_runtime_discovery_treats_public_email_form_as_test_data_not_auth(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="55555555-5555-5555-5555-555555555555",
        filename="public.apk",
        sha256="5" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    email = DiscoveredControl(
        control_id="newsletter-email",
        semantic_label="Email",
        class_name="android.widget.EditText",
        clickable=False,
        enabled=True,
        input_capable=True,
        input_kind="test_data",
        risk="review",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/email", confidence=0.98)],
    )
    subscribe = DiscoveredControl(
        control_id="subscribe",
        semantic_label="Subscribe",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="review",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/subscribe", confidence=0.98)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=1,
        control_count=2,
        safe_control_count=0,
        screens=[DiscoveredScreen(screen_id="home", fingerprint="e" * 64, controls=[email, subscribe])],
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)

    assert not any(test.bucket in {"uat", "sit"} for test in expanded.tests)
    assert not any(test.requires_auth for test in expanded.tests)
    assert any(test.requires_test_data for test in expanded.tests)


def test_runtime_expansion_promotes_deterministic_observed_cases(tmp_path):
    service = _service(tmp_path)
    analysis = AutopilotAnalysis(
        job_id="22222222-2222-2222-2222-222222222222",
        filename="investnation.apk",
        sha256="1" * 64,
        tests=service._build_deterministic_tests({"permissions": []}),
    )
    help_control = DiscoveredControl(
        control_id="help",
        semantic_label="Help",
        class_name="android.widget.Button",
        clickable=True,
        enabled=True,
        input_capable=False,
        risk="safe",
        locators=[DiscoveryLocator(strategy="id", value="com.example:id/help", confidence=0.99)],
    )
    discovery = AutopilotDiscoveryResult(
        job_id=analysis.job_id,
        status="completed",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:05+00:00",
        duration_seconds=5,
        device_name="Android Emulator",
        screen_count=1,
        control_count=1,
        safe_control_count=1,
        screens=[DiscoveredScreen(screen_id="home", fingerprint="b" * 64, controls=[help_control])],
    )

    expanded = service.expand_discovered_coverage(analysis, discovery)
    bundle = AutopilotIRCompiler().compile_bundle(expanded, discovery)

    assert bundle.discovery_used is True
    assert bundle.promoted_count >= 2
    assert any(item.bucket == "functional_positive" and item.readiness == "executable" for item in bundle.tests)
    assert any(item.bucket == "accessibility" and item.readiness == "executable" for item in bundle.tests)


def test_suite_result_never_exposes_worker_evidence_path(tmp_path):
    result = AutopilotSuiteResult(
        job_id="33333333-3333-3333-3333-333333333333",
        status="partial",
        provider="appium",
        started_at="2026-09-05T00:00:00+00:00",
        finished_at="2026-09-05T00:00:01+00:00",
        duration_seconds=1,
        device_name="Android Emulator",
        tests=[
            AutopilotSuiteTestResult(
                test_id="QT-RUNTIME-1",
                title="Safe observed control",
                status="passed",
                evidence={"evidence_dir": str(tmp_path / "private-worker-dir")},
            )
        ],
    )

    sanitized = _strip_suite_evidence_paths(result)

    assert sanitized.tests[0].evidence == {}


@pytest.mark.asyncio
async def test_report_cleanup_preserves_legacy_source_without_repository_asset(tmp_path):
    service = _service(tmp_path)
    job_id = "11111111-1111-1111-1111-111111111111"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    source = job_dir / "investnation.apk"
    source.write_bytes(b"legacy source")
    (job_dir / "job.json").write_text("{}", encoding="utf-8")
    (job_dir / "analysis.json").write_text("{}", encoding="utf-8")
    execution_dir = job_dir / "executions"
    execution_dir.mkdir()
    (execution_dir / "run.json").write_text("{}", encoding="utf-8")

    removed, source_preserved = await _remove_local_report_data(
        service,
        job_id,
        {"filename": source.name, "apk_path": str(source)},
        preserve_source=True,
    )

    assert removed is True
    assert source_preserved is True
    assert source.exists()
    assert not (job_dir / "job.json").exists()
    assert not (job_dir / "analysis.json").exists()
    assert not execution_dir.exists()


@pytest.mark.asyncio
async def test_report_cleanup_removes_repository_materialization(tmp_path):
    service = _service(tmp_path)
    job_id = "22222222-2222-2222-2222-222222222222"
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "investnation.apk").write_bytes(b"materialized source")
    (job_dir / "job.json").write_text("{}", encoding="utf-8")

    removed, source_preserved = await _remove_local_report_data(
        service,
        job_id,
        {"filename": "investnation.apk", "apk_path": str(job_dir / "investnation.apk")},
        preserve_source=False,
    )

    assert removed is True
    assert source_preserved is False
    assert not job_dir.exists()


def test_autopilot_classifies_ai_suites_and_setup_dependencies(tmp_path):
    service = _service(tmp_path)

    assert service._classify_test_bucket("UAT", "primary customer acceptance") == "uat"
    assert service._classify_test_bucket("API contracts", "backend timeout") == "integration"
    assert service._classify_test_bucket("Functional", "successful sign in") == "functional"
    dependency = service._ai_dependency("uat", True, True, False)
    assert dependency is not None
    assert "credential reference" in dependency
    assert "signed-off acceptance criteria" in dependency


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


def test_ai_business_cases_are_held_until_runtime_evidence(tmp_path):
    service = _service(tmp_path)
    cases = [
        AutopilotTest(
            id="QT-AI-001",
            suite="Functional",
            bucket="functional",
            title="SIP investment journey",
            objective="Create a SIP investment",
            steps=["Log in", "Submit investment"],
            source="ai",
            requires_auth=True,
            requires_test_data=True,
        ),
        AutopilotTest(
            id="QT-AI-002",
            suite="Accessibility",
            bucket="accessibility",
            title="Public heading semantics",
            objective="Check headings on the observed page",
            steps=["Inspect headings"],
            source="ai",
        ),
        AutopilotTest(
            id="QT-AI-003",
            suite="Functional",
            bucket="functional",
            title="Account overview journey",
            objective="Open the customer's account overview",
            steps=["Open account overview"],
            source="ai",
        ),
    ]

    kept, held_back = service._filter_unobserved_ai_tests(
        cases,
        {"platform": "web", "web_title": "Public home", "web_url": "https://example.test"},
    )

    assert [test.id for test in kept] == ["QT-AI-002"]
    assert held_back == 2


def test_initial_ai_questions_do_not_become_guessed_checkpoints(tmp_path):
    service = _service(tmp_path)
    questions = service._filter_initial_clarification_questions(
        [
            "Which environment should be tested?",
            "Please provide the login password.",
            "Do you have SIP test data?",
            "Which actions are prohibited?",
        ],
        {"platform": "web", "web_url": "https://example.test"},
    )

    assert questions == [
        "Which environment should be tested?",
        "Which actions are prohibited?",
    ]


def test_public_web_plan_has_no_guessed_checkpoint_inputs(tmp_path):
    service = _service(tmp_path)
    tests = service._build_deterministic_tests(
        {
            "platform": "web",
            "web_title": "InvestNation public home",
            "web_url": "https://investnation.com",
            "web_link_count": 12,
            "web_form_count": 2,
            "web_input_count": 3,
            "web_button_count": 4,
            "web_links": [{"text": "Help Center", "href": "/help-center/"}],
        }
    )

    assert tests
    assert all(not test.requires_auth and not test.requires_test_data for test in tests)
    assert not {test.bucket for test in tests} & {"uat", "sit", "integration"}
    bundle = AutopilotIRCompiler().compile_bundle(
        AutopilotAnalysis(
            job_id="44444444-4444-4444-4444-444444444444",
            filename="investnation.com",
            platform="web",
            target_kind="web",
            target_url="https://investnation.com",
            sha256="3" * 64,
            tests=tests,
        )
    )
    assert bundle.setup_missing_fields == []


def test_appium_connection_errors_are_blocked_not_product_failures():
    exc = RuntimeError("HTTPConnectionPool: connection refused")
    assert AutopilotPrototypeService._looks_like_connector_problem(exc) is True


def test_hosted_appium_requires_a_reachable_endpoint(tmp_path):
    from app.schemas.autopilot import AutopilotExecutionRequest

    service = _service(tmp_path, APP_ENV="production")
    with pytest.raises(RuntimeError, match="not configured"):
        service.resolve_appium_url(AutopilotExecutionRequest(provider="appium"))


def test_hosted_appium_rejects_loopback_endpoints(tmp_path):
    from app.schemas.autopilot import AutopilotExecutionRequest

    service = _service(tmp_path, APP_ENV="production")
    with pytest.raises(RuntimeError, match="cannot reach"):
        service.resolve_appium_url(
            AutopilotExecutionRequest(provider="appium", appium_url="http://127.0.0.1:4723")
        )


def test_local_appium_keeps_loopback_convenience(tmp_path):
    from app.schemas.autopilot import AutopilotExecutionRequest

    service = _service(tmp_path, APP_ENV="local")
    assert service.resolve_appium_url(AutopilotExecutionRequest(provider="appium")) == "http://127.0.0.1:4723"


def test_hosted_appium_accepts_explicit_https_endpoint(tmp_path):
    from app.schemas.autopilot import AutopilotExecutionRequest

    service = _service(tmp_path, APP_ENV="production")
    assert service.resolve_appium_url(
        AutopilotExecutionRequest(provider="appium", appium_url="https://appium.example.test/wd/hub/")
    ) == "https://appium.example.test/wd/hub"


def test_app_launch_failures_are_recorded_as_failures_not_connector_blocks():
    exc = RuntimeError(
        "An unknown server-side error occurred while processing the command. "
        "Cannot start the application; the main activity never started."
    )
    assert AutopilotPrototypeService._looks_like_connector_problem(exc) is False


def test_safe_smoke_auto_grants_permissions_by_default():
    from app.schemas.autopilot import AutopilotExecutionRequest

    assert AutopilotExecutionRequest().auto_grant_permissions is True


def test_missing_browserstack_configuration_is_blocked_not_product_failure():
    exc = RuntimeError(
        "BrowserStack is not configured. Set BROWSERSTACK_USERNAME and BROWSERSTACK_ACCESS_KEY as backend secrets."
    )
    assert AutopilotPrototypeService._looks_like_connector_problem(exc) is True


def test_runtime_state_rejects_android_anr_dialog():
    page_source = (
        '<node package="android" text="Pixel Launcher isn\'t responding" '
        'resource-id="android:id/aerr_close" />'
    )

    with pytest.raises(RuntimeError, match="ANR"):
        AutopilotPrototypeService._validate_runtime_state(
            page_source,
            "com.fhc.InvestNation.uat",
            "com.fhc.InvestNation.uat",
        )


def test_runtime_state_rejects_wrong_foreground_package():
    page_source = '<node package="com.android.launcher" text="Home" />'

    with pytest.raises(RuntimeError, match="expected"):
        AutopilotPrototypeService._validate_runtime_state(
            page_source,
            "com.android.launcher",
            "com.fhc.InvestNation.uat",
        )


def test_runtime_state_accepts_expected_application():
    page_source = '<node package="com.fhc.InvestNation.uat" text="InvestNation" />'

    AutopilotPrototypeService._validate_runtime_state(
        page_source,
        "com.fhc.InvestNation.uat",
        "com.fhc.InvestNation.uat",
    )


def test_browserstack_configuration_requires_both_secrets(tmp_path):
    incomplete = _service(tmp_path, BROWSERSTACK_USERNAME="user")
    configured = _service(
        tmp_path,
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
    )

    assert incomplete.settings.browserstack_configured is False
    assert configured.settings.browserstack_configured is True


@pytest.mark.asyncio
async def test_browserstack_smoke_does_not_resolve_custom_appium_endpoint(tmp_path, monkeypatch):
    """A configured BrowserStack run must use the BrowserStack hub directly.

    The custom Appium resolver intentionally fails closed in hosted mode. It
    must therefore never run for a BrowserStack request, otherwise a valid
    cloud run is incorrectly blocked before the APK upload/session starts.
    """
    service = _service(
        tmp_path,
        BROWSERSTACK_USERNAME="user",
        BROWSERSTACK_ACCESS_KEY="key",
    )
    apk_path = tmp_path / "investnation.apk"
    apk_path.write_bytes(b"apk")
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-4111-8111-111111111111",
        filename=apk_path.name,
        sha256="a" * 64,
        app_name="Investnation",
        package_name="com.example.investnation",
    )

    async def load_job(_job_id):
        return {"apk_path": str(apk_path), "filename": apk_path.name}

    async def load_analysis(_job_id):
        return analysis

    async def browserstack_app_url(_job_id, _path, _sha256):
        return "bs://investnation"

    def fail_if_custom_resolver_called(_request):
        raise AssertionError("BrowserStack execution must not resolve custom Appium")

    captured = {}

    def fake_execute(
        appium_url,
        app_reference,
        _request,
        screenshot_path,
        source_path,
        browserstack_options=None,
        *_timeouts,
    ):
        captured.update(
            url=appium_url,
            app=app_reference,
            options=browserstack_options,
        )
        screenshot_path.write_bytes(b"png")
        source_path.write_text(
            '<node package="com.example.investnation" text="Investnation" />',
            encoding="utf-8",
        )
        return {"current_package": "com.example.investnation"}

    async def skip_persist(_execution, _request):
        return None

    monkeypatch.setattr(service, "load_job", load_job)
    monkeypatch.setattr(service, "load_analysis", load_analysis)
    monkeypatch.setattr(service, "_browserstack_app_url", browserstack_app_url)
    monkeypatch.setattr(service, "resolve_appium_url", fail_if_custom_resolver_called)
    monkeypatch.setattr(service, "_execute_appium_sync", fake_execute)
    monkeypatch.setattr(service, "_persist_execution_file", skip_persist)

    result = await service.execute_smoke(
        analysis.job_id,
        AutopilotExecutionRequest(provider="browserstack"),
    )

    assert result.status == "passed"
    assert captured["url"] == service.settings.BROWSERSTACK_HUB_URL
    assert captured["app"] == "bs://investnation"
    assert captured["options"]["userName"] == "user"
    assert captured["options"]["accessKey"] == "key"


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


def test_default_context_is_fintech_and_guardrail_focused():
    assert "CBUAE" in DEFAULT_AUTOPILOT_CONTEXT
    assert "SCA" in DEFAULT_AUTOPILOT_CONTEXT
    assert "Application: [TO CONFIRM]" in DEFAULT_AUTOPILOT_CONTEXT
    assert "Investnation" not in DEFAULT_AUTOPILOT_CONTEXT
    assert "remain pending" in DEFAULT_AUTOPILOT_CONTEXT


def test_profile_catalog_renders_a_dynamic_brief():
    profiles = list_profiles()
    ids = {profile.id for profile in profiles}

    assert DEFAULT_AUTOPILOT_PROFILE_ID in ids
    assert "payments_cards" in ids
    assert "Profile category: UAE Digital Banking & Wealth" in DEFAULT_AUTOPILOT_CONTEXT
    assert "CBUAE/SCA" in profile_context(DEFAULT_AUTOPILOT_PROFILE_ID)
    assert "Investnation" not in profile_context(DEFAULT_AUTOPILOT_PROFILE_ID)
    assert "wallet" in profile_context("payments_cards").lower()


def test_profile_context_uses_only_explicit_application_identity():
    assert "Application: [TO CONFIRM]" in profile_context(DEFAULT_AUTOPILOT_PROFILE_ID)
    assert "Investnation by Finance House" in profile_context(
        DEFAULT_AUTOPILOT_PROFILE_ID,
        application_name="Investnation by Finance House",
    )


def test_profile_context_sanitizes_website_state_and_credentials():
    context = profile_context(
        DEFAULT_AUTOPILOT_PROFILE_ID,
        platform="Web",
        target_url="https://user:secret@example.com/uat?invite=token#fragment",
    )

    assert "secret" not in context
    assert "invite" not in context
    assert "Target URL: https://example.com/uat" in context


def test_surface_identity_is_stable_and_secret_free():
    identity = normalize_surface_identity(
        "web",
        target_url="https://example.com/uat?session=secret#fragment",
    )

    assert identity == "https://example.com/uat"
    assert "secret" not in identity
    assert build_surface_key("uae_fintech", "web", identity) != build_surface_key("payments_cards", "web", identity)


def test_report_tab_key_keeps_new_versions_independently_selectable():
    scope_key = build_surface_key("uae_fintech", "android", "sha256:release")

    first = build_report_tab_key(scope_key, 1, "job-one")
    second = build_report_tab_key(scope_key, 2, "job-two")

    assert first != second
    assert scope_key in first and scope_key in second
    assert first.endswith(":1:job-one")
    assert second.endswith(":2:job-two")


def test_ai_context_keeps_selected_surface_identity():
    baseline = profile_context(
        DEFAULT_AUTOPILOT_PROFILE_ID,
        application_name="release-2026.08.apk",
        platform="Android",
    )
    enriched = AutopilotPrototypeService._ensure_context_identity(
        "Target audience: UAE retail investors.\nCore features: onboarding and portfolios.",
        baseline,
    )

    assert "Profile category: UAE Digital Banking & Wealth" in enriched
    assert "Application: release-2026.08.apk" in enriched
    assert "Target: Android" in enriched


@pytest.mark.asyncio
async def test_ai_enrichment_receives_selected_context_as_a_first_class_scope(tmp_path, monkeypatch):
    service = _service(tmp_path)
    captured = {}

    class FakeProvider:
        async def complete(self, messages, **_kwargs):
            captured["messages"] = messages
            from types import SimpleNamespace

            return SimpleNamespace(
                content=(
                    '{"app_summary":"Context-aware summary",'
                    '"inferred_domain":"Banking / Financial Services",'
                    '"critical_journeys":["UAE PASS onboarding"],'
                    '"clarification_questions":[],"release_risks":[],"tests":[]}'
                )
            )

    monkeypatch.setattr("app.services.autopilot.get_llm_provider", lambda: FakeProvider())
    result = await service._enrich_with_ai(
        {"platform": "android", "permissions": [], "activities": []},
        "Profile category: UAE Digital Banking & Wealth\nPrioritise UAE PASS onboarding and CBUAE audit logging.",
    )

    assert result["_ai_used"] is True
    assert "UAE PASS onboarding" in captured["messages"][1].content
    assert "first-class testing scope" in captured["messages"][1].content
    assert "context claims are not observed evidence" in captured["messages"][0].content


def test_report_never_claims_runtime_pass_rate_without_execution():
    from app.schemas.autopilot import AutopilotAnalysis

    analysis = AutopilotAnalysis(
        job_id="11111111-1111-4111-8111-111111111111",
        filename="investnation.apk",
        sha256="a" * 64,
        app_name="Investnation",
        package_name="com.example.investnation",
        permissions=["android.permission.INTERNET"],
    )
    report = build_test_audit_report(analysis, DEFAULT_AUTOPILOT_CONTEXT)

    assert report.recommendation == "PENDING"
    assert report.metrics.executed_test_cases is None
    assert report.metrics.pass_rate is None
    assert report.metrics.defect_count is None
    assert report.last_run_at is None
    assert report.risk_matrix == []
    assert report.application_overview.name == "Investnation"
    assert all(check.status == "pending" for check in report.compliance_verification)
    assert all(check.dependency for check in report.compliance_verification)


def test_report_pass_rate_uses_all_designed_cases_as_denominator():
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-4111-8111-111111111111",
        filename="investnation.apk",
        sha256="a" * 64,
        app_name="Investnation",
        package_name="com.example.investnation",
        tests=[
            AutopilotTest(
                id=f"QT-FUNC-{index:03d}",
                suite="Functional",
                title=f"Functional case {index}",
                objective="Validate an observed application flow.",
            )
            for index in range(1, 6)
        ],
    )
    suite = AutopilotSuiteResult(
        job_id=analysis.job_id,
        status="partial",
        provider="appium",
        started_at="2026-09-19T00:00:00+00:00",
        finished_at="2026-09-19T00:00:01+00:00",
        duration_seconds=1,
        device_name="Test device",
        selected_count=3,
        executed_count=3,
        passed_count=2,
        tests=[
            AutopilotSuiteTestResult(test_id=f"QT-FUNC-{index:03d}", title=f"Case {index}", status="passed")
            for index in range(1, 3)
        ]
        + [AutopilotSuiteTestResult(test_id="QT-FUNC-003", title="Case 3", status="blocked")],
    )

    report = build_test_audit_report(analysis, DEFAULT_AUTOPILOT_CONTEXT, suite=suite)

    assert report.metrics.designed_test_cases == 5
    assert report.metrics.executed_test_cases == 3
    assert report.metrics.passed_count == 2
    assert report.metrics.pass_rate == 40.0


def test_report_preserves_user_stated_modules_as_unverified_scope():
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-4111-8111-111111111199",
        filename="FH_Money.apk",
        sha256="c" * 64,
        app_name="FH Money",
        package_name="com.fh.payday",
        tests=[],
    )

    report = build_test_audit_report(
        analysis,
        "Testing scope: Functional only\nModules: Login, Profile, Cards, Send Money",
    )

    assert report.application_overview.core_features[0].startswith(
        "User-stated modules (runtime confirmation pending):"
    )
    assert "Send Money" in report.application_overview.core_features[0]


def test_report_exposes_durable_functional_video_assets():
    analysis = AutopilotAnalysis(
        job_id="11111111-1111-4111-8111-111111111111",
        filename="investnation.apk",
        sha256="a" * 64,
        app_name="Investnation",
        package_name="com.example.investnation",
        tests=[],
    )
    suite = AutopilotSuiteResult(
        job_id=analysis.job_id,
        status="passed",
        provider="appium",
        started_at="2026-09-04T00:00:00+00:00",
        finished_at="2026-09-04T00:00:01+00:00",
        duration_seconds=1,
        device_name="Test device",
        selected_count=1,
        executed_count=1,
        passed_count=1,
        tests=[
            AutopilotSuiteTestResult(
                test_id="QT-FUNC-001",
                title="Complete the safe login journey",
                status="passed",
                bucket="functional",
                evidence={
                    "evidence_assets": [
                        {
                            "asset_id": "22222222-2222-4222-8222-222222222222",
                            "filename": "functional-journey.mp4",
                            "kind": "video",
                        }
                    ]
                },
            )
        ],
    )

    report = build_test_audit_report(analysis, DEFAULT_AUTOPILOT_CONTEXT, suite=suite)

    assert len(report.evidence_assets) == 1
    assert report.evidence_assets[0].kind == "video"
    assert report.evidence_assets[0].bucket == "functional"
    assert "functional video" in " ".join(report.evidence)


@pytest.mark.asyncio
async def test_stale_discovery_evidence_ids_are_removed_at_read_boundary():
    available = UUID("11111111-1111-4111-8111-111111111111")
    stale = UUID("22222222-2222-4222-8222-222222222222")

    class FakeScalars:
        def all(self):
            return [available]

    class FakeDb:
        async def scalars(self, _query):
            return FakeScalars()

    discovery = AutopilotDiscoveryResult(
        job_id="33333333-3333-4333-8333-333333333333",
        status="completed",
        provider="playwright",
        started_at="2026-09-04T00:00:00+00:00",
        finished_at="2026-09-04T00:00:01+00:00",
        duration_seconds=1,
        device_name="Chromium",
        screens=[
            DiscoveredScreen(
                screen_id="screen-001",
                fingerprint="fingerprint",
                screenshot_asset_id=available,
                page_source_asset_id=stale,
            )
        ],
    )
    sanitized = await _sanitize_discovery_assets(
        FakeDb(),
        SimpleNamespace(id=UUID("44444444-4444-4444-8444-444444444444")),
        SimpleNamespace(project_id=UUID("55555555-5555-4555-8555-555555555555")),
        discovery,
    )

    assert sanitized is not None
    assert sanitized.screens[0].screenshot_asset_id == available
    assert sanitized.screens[0].page_source_asset_id is None


def test_failed_retry_keeps_last_usable_discovery_snapshot():
    """A provider/system-UI retry must not erase the authenticated map."""
    previous = AutopilotDiscoveryResult(
        job_id="33333333-3333-4333-8333-333333333333",
        status="completed",
        provider="appium",
        started_at="2026-09-04T00:00:00+00:00",
        finished_at="2026-09-04T00:00:01+00:00",
        duration_seconds=1,
        device_name="Android emulator",
        target_ready=True,
        target_identity="com.example.investnation",
        screen_count=1,
        screens=[DiscoveredScreen(
            screen_id="screen-001",
            fingerprint="a" * 64,
            package_name="com.example.investnation",
            page_label="Home",
        )],
    )
    latest = AutopilotDiscoveryResult(
        job_id=previous.job_id,
        status="blocked",
        provider="appium",
        started_at="2026-09-04T00:01:00+00:00",
        finished_at="2026-09-04T00:01:02+00:00",
        duration_seconds=2,
        device_name="Android emulator",
        target_ready=False,
        target_identity="android",
        target_identity_reason="Runtime session reached only Android system UI; the uploaded application was not launched.",
        stop_reason="Target was not attached",
        screen_count=0,
        screens=[],
    )

    merged = _merge_discovery_snapshot(previous, latest)

    assert [screen.screen_id for screen in merged.screens] == ["screen-001"]
    assert merged.target_ready is True
    assert merged.last_attempt_status == "blocked"
    assert "system UI" in (merged.last_attempt_reason or "")
    assert any("Latest discovery attempt blocked" in warning for warning in merged.warnings)


def test_successful_retry_replaces_old_discovery_snapshot():
    previous = AutopilotDiscoveryResult(
        job_id="44444444-4444-4444-8444-444444444444",
        status="completed",
        provider="appium",
        started_at="2026-09-04T00:00:00+00:00",
        finished_at="2026-09-04T00:00:01+00:00",
        duration_seconds=1,
        device_name="Android emulator",
        target_ready=True,
        screen_count=1,
        screens=[DiscoveredScreen(screen_id="old", fingerprint="b" * 64)],
    )
    latest = previous.model_copy(update={
        "finished_at": "2026-09-04T00:02:00+00:00",
        "screen_count": 1,
        "screens": [DiscoveredScreen(screen_id="new", fingerprint="c" * 64)],
        "last_attempt_status": None,
        "target_ready": True,
    })

    merged = _merge_discovery_snapshot(previous, latest)

    assert [screen.screen_id for screen in merged.screens] == ["new"]
    assert merged.last_attempt_status is None


@pytest.mark.asyncio
async def test_background_analysis_records_failure_instead_of_hanging(tmp_path, monkeypatch):
    service = _service(tmp_path)
    job_id, _ = await service.save_upload("broken.apk", b"x" * 2048, "owner")

    async def fail(_job_id):
        raise RuntimeError("parser stopped")

    monkeypatch.setattr(service, "analyze", fail)
    await service.analyze_safely(job_id)
    result = await service.get_job_status(job_id)

    assert result.status == "failed"
    assert result.progress == 100
    assert "parser stopped" in (result.error or "")


@pytest.mark.asyncio
async def test_completed_background_analysis_returns_saved_result(tmp_path, monkeypatch):
    service = _service(tmp_path)
    job_id, _ = await service.save_upload("app.apk", b"x" * 2048, "owner")

    async def complete(_job_id):
        from app.schemas.autopilot import AutopilotAnalysis
        result = AutopilotAnalysis(job_id=job_id, filename="app.apk", sha256="a" * 64)
        service._metadata_path(job_id).write_text(result.model_dump_json(), encoding="utf-8")
        return result

    monkeypatch.setattr(service, "analyze", complete)
    await service.analyze_safely(job_id)
    result = await service.get_job_status(job_id)

    assert result.status == "analyzed"
    assert result.analysis is not None


@pytest.mark.asyncio
async def test_analysis_enters_runtime_discovery_before_static_references(tmp_path, monkeypatch):
    service = _service(tmp_path)
    job_id, _ = await service.save_upload("investnation.apk", b"x" * 2048, "owner")

    async def checkpoint_analysis(_job_id):
        from app.schemas.autopilot import AutopilotAnalysis, AutopilotTest

        result = AutopilotAnalysis(
            job_id=job_id,
            filename="investnation.apk",
            sha256="a" * 64,
            tests=[
                AutopilotTest(
                    id="QT-AUTO-FUNC-001",
                    suite="Functional",
                    title="Authenticate investor",
                    objective="Validate a safe sign-in",
                    requires_auth=True,
                    requires_test_data=True,
                )
            ],
        )
        service._metadata_path(job_id).write_text(result.model_dump_json(), encoding="utf-8")
        return result

    monkeypatch.setattr(service, "analyze", checkpoint_analysis)
    await service.analyze_safely(job_id)

    pending = await service.get_job_status(job_id)
    # Static analysis cannot know whether the target actually exposes a login
    # form. Runtime Discovery must invoke it first and surface field-level
    # User ID/password questions from the observed screen.
    assert pending.status == "analyzed"
    assert pending.checkpoint_stage == "ready_for_discovery"
    assert pending.input_requests == []

    await service.update_job(
        job_id,
        setup_profile={
            "job_id": job_id,
            "credential_reference": "qtxpert://credentials/investnation-uat",
            "account_role": "UAT investor",
            "environment_name": "UAT",
            "test_data_reference": "qtxpert://data/investnation-synthetic",
            "reset_hook_reference": "qtxpert://hooks/investnation-reset",
            "safe_authentication_approved": True,
        },
    )
    await service.resume_analysis(job_id, allow_runtime_discovery=True)
    resumed = await service.get_job_status(job_id)
    assert resumed.status == "analyzed"
    assert resumed.checkpoint_stage == "ready_for_discovery"
    assert resumed.input_requests == []


@pytest.mark.asyncio
async def test_resume_rebuilds_missing_snapshot_from_available_source(tmp_path, monkeypatch):
    """A disposable Render filesystem must not turn a saved checkpoint into a loop."""
    service = _service(tmp_path)
    job_id, apk_path = await service.save_upload("investnation.apk", b"x" * 2048, "owner")
    rebuilt = AutopilotAnalysis(
        job_id=job_id,
        filename="investnation.apk",
        sha256="b" * 64,
        app_name="Investnation",
    )
    calls = 0

    async def rebuild(_job_id):
        nonlocal calls
        calls += 1
        return rebuilt

    monkeypatch.setattr(service, "analyze", rebuild)
    assert not service._metadata_path(job_id).exists()
    assert apk_path.exists()

    await service.resume_analysis(job_id)
    resumed = await service.get_job_status(job_id)

    assert calls == 1
    assert resumed.status == "analyzed"
    assert resumed.analysis is not None


@pytest.mark.asyncio
async def test_large_upload_stream_is_written_incrementally(tmp_path):
    service = _service(tmp_path)

    class FakeUpload:
        def __init__(self):
            self.chunks = [b"a" * 1024, b"b" * 1024, b""]

        async def read(self, _size):
            return self.chunks.pop(0)

    job_id, path = await service.save_upload_stream(
        "large.apk",
        FakeUpload(),
        "owner",
        max_bytes=4096,
    )

    assert path.read_bytes() == b"a" * 1024 + b"b" * 1024
    assert (tmp_path / job_id / "job.json").exists()


def test_large_apk_uses_safe_zip_inventory_without_shadowing_zipfile(tmp_path):
    """A large APK follows the metadata-only path without a parser error.

    The previous fallback imported ``zipfile`` inside the exception branch,
    which made Python treat it as a local variable and raised
    ``UnboundLocalError`` before the ZIP inventory could be read.
    """
    apk_path = tmp_path / "large-release.apk"
    with zipfile.ZipFile(apk_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("assets/payload.bin", b"x" * (2 * 1024 * 1024))

    service = _service(tmp_path, AUTOPILOT_DEEP_PARSE_MAX_MB=1)
    result = service._analyze_apk_sync(apk_path)

    assert result["file_count"] == 1
    assert any("bounded archive metadata" in warning for warning in result["warnings"])
    assert not any("UnboundLocalError" in warning for warning in result["warnings"])


def _fixture_binary_manifest() -> bytes:
    """Build a small binary-XML manifest for bounded large-APK coverage."""
    values = [
        "android",
        "http://schemas.android.com/apk/res/android",
        "manifest",
        "application",
        "activity",
        "intent-filter",
        "action",
        "category",
        "uses-sdk",
        "uses-permission",
        "package",
        "versionName",
        "versionCode",
        "minSdkVersion",
        "targetSdkVersion",
        "name",
        "label",
        "debuggable",
        "com.example.investnation",
        "Investnation",
        "27",
        "23",
        "34",
        "com.example.investnation.MainActivity",
        "android.intent.action.MAIN",
        "android.intent.category.LAUNCHER",
        "android.permission.INTERNET",
        "1.2.3",
        "true",
    ]
    index = {value: number for number, value in enumerate(values)}

    def length8(number: int) -> bytes:
        return bytes([number]) if number < 0x80 else bytes([((number >> 7) & 0x7F) | 0x80, number & 0x7F])

    strings = b"".join(length8(len(value.encode("utf-8"))) + length8(len(value)) + value.encode("utf-8") + b"\0" for value in values)
    offsets: list[int] = []
    cursor = 0
    for value in values:
        offsets.append(cursor)
        cursor += len(length8(len(value.encode("utf-8"))) + length8(len(value)) + value.encode("utf-8") + b"\0")
    pool_header_size = 28
    pool_size = pool_header_size + len(offsets) * 4 + len(strings)
    pool = struct.pack(
        "<HHI5I",
        0x0001,
        pool_header_size,
        pool_size,
        len(values),
        0,
        0x100,
        pool_header_size + len(offsets) * 4,
        0,
    ) + struct.pack(f"<{len(offsets)}I", *offsets) + strings

    def start_namespace() -> bytes:
        return struct.pack(
            "<HHI4I",
            0x0100,
            16,
            24,
            1,
            0,
            index["android"],
            index["http://schemas.android.com/apk/res/android"],
        )

    def start_element(name: str, attrs: list[tuple[str, str, str | None]]) -> bytes:
        attr_bytes = b""
        for attr_name, attr_value, raw_value in attrs:
            raw_index = 0xFFFFFFFF if raw_value is None else index[raw_value]
            value_index = index[attr_value] if attr_value in index else 0
            attr_bytes += struct.pack(
                "<IIIHBBI",
                0xFFFFFFFF if attr_name == "package" else index["http://schemas.android.com/apk/res/android"],
                index[attr_name],
                raw_index,
                8,
                0,
                0x03,
                value_index,
            )
        return (
            struct.pack(
                "<HHI4I6H",
                0x0102,
                16,
                36 + len(attr_bytes),
                1,
                0,
                0,
                index[name],
                20,
                20,
                len(attrs),
                0,
                0,
                0,
            )
            + attr_bytes
        )

    def end_element(name: str) -> bytes:
        return struct.pack("<HHI4I", 0x0103, 16, 24, 1, 0, 0, index[name])

    chunks = [
        pool,
        start_namespace(),
        start_element(
            "manifest",
            [("package", "com.example.investnation", None), ("versionName", "1.2.3", None), ("versionCode", "27", None)],
        ),
        start_element("uses-sdk", [("minSdkVersion", "23", None), ("targetSdkVersion", "34", None)]),
        end_element("uses-sdk"),
        start_element("uses-permission", [("name", "android.permission.INTERNET", None)]),
        end_element("uses-permission"),
        start_element("application", [("label", "Investnation", None), ("debuggable", "true", None)]),
        start_element("activity", [("name", "com.example.investnation.MainActivity", None)]),
        start_element("intent-filter", []),
        start_element("action", [("name", "android.intent.action.MAIN", None)]),
        end_element("action"),
        start_element("category", [("name", "android.intent.category.LAUNCHER", None)]),
        end_element("category"),
        end_element("intent-filter"),
        end_element("activity"),
        end_element("application"),
        end_element("manifest"),
    ]
    body = b"".join(chunks)
    return struct.pack("<HHI", 0x0003, 8, 8 + len(body)) + body


def test_large_apk_recovers_binary_manifest_identity_for_runtime_launch(tmp_path):
    apk_path = tmp_path / "large-release.apk"
    with zipfile.ZipFile(apk_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AndroidManifest.xml", _fixture_binary_manifest())
        archive.writestr("assets/payload.bin", b"x" * (2 * 1024 * 1024))

    service = _service(tmp_path, AUTOPILOT_DEEP_PARSE_MAX_MB=1)
    result = service._analyze_apk_sync(apk_path)

    assert result["package_name"] == "com.example.investnation"
    assert result["main_activity"] == "com.example.investnation.MainActivity"
    assert result["activities"] == ["com.example.investnation.MainActivity"]
    assert "android.permission.INTERNET" in result["permissions"]
    assert result["min_sdk"] == "23"
    assert result["target_sdk"] == "34"
    assert result["debuggable"] is True


@pytest.mark.asyncio
async def test_legacy_discovery_refreshes_missing_apk_identity_before_launch(tmp_path):
    """A pre-manifest job is repaired from its stored APK on discovery retry."""
    apk_path = tmp_path / "legacy-release.apk"
    with zipfile.ZipFile(apk_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AndroidManifest.xml", _fixture_binary_manifest())
        archive.writestr("assets/payload.bin", b"x" * (2 * 1024 * 1024))

    service = _service(tmp_path, AUTOPILOT_DEEP_PARSE_MAX_MB=1)
    job_id, _ = await service.save_upload("legacy-release.apk", apk_path.read_bytes(), "owner")
    stale = AutopilotAnalysis(
        job_id=job_id,
        filename="legacy-release.apk",
        sha256="f" * 64,
        target_kind="android",
        platform="android",
        package_name=None,
        main_activity=None,
    )
    (tmp_path / job_id / "analysis.json").write_text(stale.model_dump_json(indent=2), encoding="utf-8")

    refreshed = await _refresh_mobile_analysis_identity(
        service,
        job_id,
        stale,
        artifact_path=tmp_path / job_id / "legacy-release.apk",
    )

    assert refreshed is not None
    assert refreshed.package_name == "com.example.investnation"
    assert refreshed.main_activity == "com.example.investnation.MainActivity"
    saved = AutopilotAnalysis.model_validate_json(
        (tmp_path / job_id / "analysis.json").read_text(encoding="utf-8")
    )
    assert saved.package_name == refreshed.package_name


def test_large_apk_upload_limit_is_separate_from_deep_parse_limit(tmp_path):
    service = _service(tmp_path)

    assert service.settings.AUTOPILOT_MAX_UPLOAD_SIZE_MB == 300
    assert service.settings.AUTOPILOT_DEEP_PARSE_MAX_MB == 64


@pytest.mark.asyncio
async def test_local_staging_cleanup_removes_only_stale_atomic_files(tmp_path):
    service = _service(tmp_path, AUTOPILOT_LOCAL_STAGING_TTL_SECONDS=300)
    job_id, artifact_path = await service.save_upload("keep.apk", b"x" * 2048, "owner")
    stale_part = tmp_path / job_id / "old.apk.part"
    stale_tmp = tmp_path / job_id / "old.json.tmp"
    stale_part.write_bytes(b"orphaned")
    stale_tmp.write_bytes(b"orphaned")
    old_timestamp = time.time() - 3600
    os.utime(stale_part, (old_timestamp, old_timestamp))
    os.utime(stale_tmp, (old_timestamp, old_timestamp))

    removed = await service.cleanup_local_staging()

    assert removed == 2
    assert artifact_path.exists()
    assert (artifact_path.parent / "job.json").exists()


@pytest.mark.asyncio
async def test_reused_repository_asset_is_queued_without_copying_bytes(tmp_path):
    """Reusing a stored build returns a status before its bytes are copied."""
    service = _service(tmp_path)
    asset_id = UUID("11111111-1111-4111-8111-111111111111")

    job_id, artifact_path = await service.save_reused_asset_job(
        "release.apk",
        "owner",
        asset_id,
        context="safe test context",
        target_kind="android",
    )

    assert not artifact_path.exists()
    manifest = json.loads((artifact_path.parent / "job.json").read_text(encoding="utf-8"))
    assert manifest["repository_asset_id"] == str(asset_id)
    assert manifest["artifact_materialization"] == "queued"
    status = await service.get_job_status(job_id)
    assert status.status == "uploaded"
    assert status.artifact_available is True


@pytest.mark.asyncio
async def test_stream_upload_cleans_partial_job_when_too_large(tmp_path):
    service = _service(tmp_path)

    class FakeUpload:
        async def read(self, _size):
            return b"x" * 2048

    with pytest.raises(AutopilotUploadTooLarge):
        await service.save_upload_stream("too-large.apk", FakeUpload(), "owner", max_bytes=1024)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_latest_job_status_is_owner_scoped(tmp_path):
    service = _service(tmp_path)
    job_id, _ = await service.save_upload("latest.apk", b"x" * 2048, "owner")

    latest = await service.get_latest_job_status("owner")
    assert latest is not None
    assert latest.job_id == job_id
    assert await service.get_latest_job_status("another-owner") is None


@pytest.mark.asyncio
async def test_execution_history_files_are_per_run_and_reusable(tmp_path):
    from app.api.routes.autopilot import _execution_record_from_file
    from app.schemas.autopilot import AutopilotExecutionRequest, AutopilotExecutionResult

    service = _service(tmp_path)
    job_id, _ = await service.save_upload("history.apk", b"x" * 2048, "owner")
    request = AutopilotExecutionRequest(provider="appium", device_name="emulator-5554")
    result = AutopilotExecutionResult(
        execution_id="11111111-1111-4111-8111-111111111111",
        job_id=job_id,
        status="blocked",
        provider="appium",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        duration_seconds=1,
        device_name="emulator-5554",
        error="Appium is unavailable",
    )

    await service._persist_execution_file(result, request)
    records = await service.list_execution_files(job_id)

    assert len(records) == 1
    assert records[0]["execution_id"] == str(result.execution_id)
    assert records[0]["request"]["device_name"] == "emulator-5554"
    restored = _execution_record_from_file(records[0], job_id)
    assert restored is not None
    assert restored.execution_id == result.execution_id

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("current_phase", "expected_phase"),
    [
        ("plan_pending_review", "plan_approved"),
        ("exploring", "exploring"),
        ("cases_pending_review", "cases_pending_review"),
        ("execution_ready", "execution_ready"),
    ],
)
async def test_plan_approval_does_not_rewind_forward_workflow_phase(
    monkeypatch,
    current_phase,
    expected_phase,
):
    from app.api.routes import autopilot as autopilot_routes
    from app.schemas.autopilot import AutopilotGenerationPlan
    from app.services.autopilot_workflow import transition_phase

    job_id = "55555555-5555-4555-8555-555555555555"
    raw_plan = AutopilotGenerationPlan(
        plan_id=f"plan-{job_id}-v1",
        job_id=job_id,
    ).model_dump(mode="json")

    class FakeService:
        def __init__(self):
            self.job = {"job_id": job_id, "phase": current_phase}
            self.updates = []

        async def update_job(self, _job_id, **changes):
            if "phase" in changes:
                self.job["phase"] = transition_phase(self.job["phase"], changes["phase"])
            self.job.update(changes)
            self.updates.append(changes)
            return self.job

    service = FakeService()

    async def require_owned_job(_service, _job_id, _user):
        return service.job

    async def load_or_build_plan(_service, _job_id):
        return raw_plan, None

    monkeypatch.setattr(autopilot_routes, "_service", lambda _settings: service)
    monkeypatch.setattr(autopilot_routes, "_require_owned_job", require_owned_job)
    monkeypatch.setattr(autopilot_routes, "_load_or_build_autopilot_plan", load_or_build_plan)

    approved = await autopilot_routes.approve_autopilot_generation_plan(
        job_id,
        SimpleNamespace(id="owner"),
        None,
    )

    assert approved.status == "approved"
    assert approved.approval_required is False
    assert service.job["phase"] == expected_phase
    if current_phase == "plan_pending_review":
        assert service.updates[0]["phase"] == "plan_approved"
    else:
        assert "phase" not in service.updates[0]
