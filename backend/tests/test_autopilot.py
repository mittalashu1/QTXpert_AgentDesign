from pathlib import Path

import pytest

from app.config import Settings
from app.services.autopilot import AutopilotPrototypeService, AutopilotUploadTooLarge


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
