import json
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
    DiscoveredScreen,
)
from app.api.routes.autopilot import _sanitize_discovery_assets
from app.services.autopilot import (
    AutopilotPrototypeService,
    AutopilotUploadTooLarge,
    build_report_tab_key,
    build_surface_key,
    normalize_surface_identity,
)
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
        "functional",
        "uat",
        "ui",
        "accessibility",
        "integration",
        "performance",
        "security",
        "compatibility",
        "resilience",
        "permissions",
        "regression",
    }.issubset({test.bucket for test in tests})


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
async def test_analysis_pauses_for_inputs_and_resumes_after_references(tmp_path, monkeypatch):
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
    assert pending.status == "waiting_for_input"
    assert pending.analysis is not None
    assert {item.key for item in pending.input_requests} == {
        "credential_reference",
        "account_role",
        "safe_authentication_approved",
        "test_data_reference",
        "reset_hook_reference",
    }

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
    await service.resume_analysis(job_id)
    resumed = await service.get_job_status(job_id)
    assert resumed.status == "analyzed"
    assert resumed.checkpoint_stage == "ready_for_discovery"
    assert resumed.input_requests == []


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


