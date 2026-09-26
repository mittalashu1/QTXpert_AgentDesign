"""Protocol-boundary tests for project-paired local device execution."""
import importlib.util
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.routes.local_runners import _decode_evidence, _derived_lease_token, _digest
from app.api.routes import local_runners
from app.database.models.execution import ExecutionStatus, ResultStatus


ROOT = Path(__file__).resolve().parents[2]
AGENT_PATH = ROOT / "tools" / "local_runner" / "agent.py"
spec = importlib.util.spec_from_file_location("qtxpert_local_runner_agent", AGENT_PATH)
agent = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(agent)


def test_lease_secret_is_deterministic_per_runner_run_and_attempt():
    secret = "qtxrunner_test-secret"
    run_id = "25d3ce5f-22b9-4bc1-a842-0d2a300675a1"
    token = _derived_lease_token(secret, run_id, 1)
    assert token == _derived_lease_token(secret, run_id, 1)
    assert token != _derived_lease_token(secret, run_id, 2)
    assert token != _derived_lease_token(secret + "x", run_id, 1)
    assert _digest(token) != token


def test_runner_requires_https_for_cloud_but_allows_local_api_for_tests():
    assert agent.normalize_api_url("https://design.example/api/v1") == "https://design.example/api/v1"
    assert agent.normalize_api_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000/api/v1"
    with pytest.raises(ValueError, match="HTTPS"):
        agent.normalize_api_url("http://design.example")


def test_mobile_dsl_accepts_only_explicit_supported_actions():
    compiled = agent.compile_mobile_steps([
        "launch app",
        "tap accessibility_id :: Sign in",
        "fill id :: account-name :: qa-user",
        "assert-text Home",
        "assert-visible xpath :: //android.widget.Button[@text='Continue']",
        "back",
    ])
    assert [action for action, _, _ in compiled] == ["tap", "fill", "assert-text", "assert-visible", "back"]
    assert compiled[0] == ("tap", "accessibility_id", "Sign in")
    assert compiled[1] == ("fill", "id", "account-name :: qa-user")
    with pytest.raises(ValueError, match="Unsupported mobile automation step"):
        agent.compile_mobile_steps(["explore the investment page and choose something suitable"])


def test_mobile_locator_parser_rejects_unknown_strategy():
    with pytest.raises(ValueError, match="strategy"):
        agent.compile_mobile_steps(["tap css :: .submit"])


def test_evidence_upload_is_bounded_and_validated():
    assert _decode_evidence("aGVsbG8=", 5, "Screenshot") == b"hello"
    with pytest.raises(Exception, match="base64"):
        _decode_evidence("not base64!", 1024, "Screenshot")
    with pytest.raises(Exception, match="limit"):
        _decode_evidence("YWJjZGVm", 3, "Screenshot")


@pytest.mark.asyncio
async def test_runner_auth_rejects_wrong_or_revoked_identity():
    token = "qtxrunner_" + "x" * 48
    db = SimpleNamespace(scalar=AsyncMock(return_value=SimpleNamespace(runner_token_hash=_digest(token))))
    with pytest.raises(HTTPException) as error:
        await local_runners._authenticate_runner(db, uuid4(), "Bearer " + "y" * 48)
    assert error.value.status_code == 401
    db.scalar.return_value = None
    with pytest.raises(HTTPException) as error:
        await local_runners._authenticate_runner(db, uuid4(), "Bearer " + token)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_expired_lease_cannot_upload_results():
    job = SimpleNamespace(lease_token_hash=_digest("lease"), lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    db = SimpleNamespace(scalar=AsyncMock(return_value=job))
    with pytest.raises(HTTPException) as error:
        await local_runners._leased_job(db, runner_id=uuid4(), run_id=uuid4(), lease_token="lease", lock=True)
    assert error.value.status_code == 409
    assert "expired" in error.value.detail


@pytest.mark.asyncio
async def test_claim_preserves_preflight_blocks_and_returns_only_pending_cases(monkeypatch):
    runner = SimpleNamespace(id=uuid4(), owner_id=uuid4(), project_id=uuid4(), capabilities={"platforms": ["android"]})
    job = SimpleNamespace(status="queued", runner_id=None, attempt_count=0, lease_expires_at=None, execution_run_id=uuid4())
    case = SimpleNamespace(test_case_key="TC-login", scenario="Login screen is shown", steps=["assert-text Sign in"])
    pending = SimpleNamespace(id=uuid4(), status=ResultStatus.PENDING, execution_plan_case=None, test_case=case)
    blocked = SimpleNamespace(id=uuid4(), status=ResultStatus.BLOCKED)
    run = SimpleNamespace(id=job.execution_run_id, results=[pending, blocked], execution_plan=None, app_asset_id=uuid4(), project_id=runner.project_id, target_kind="android", device_name="emulator-5554", platform_version=None, target_metadata={}, started_at=None)
    asset = SimpleNamespace(id=run.app_asset_id, project_id=run.project_id, filename="app.apk", sha256="a" * 64, size_bytes=123)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[job, run]), commit=AsyncMock())
    monkeypatch.setattr(local_runners, "_authenticate_runner", AsyncMock(return_value=(runner, "secret")))
    monkeypatch.setattr(local_runners.UploadRepositoryService, "get_owned", AsyncMock(return_value=asset))
    result = await local_runners.claim_job(runner.id, db, "Bearer secret")
    assert [item["result_id"] for item in result["cases"]] == [str(pending.id)]
    assert blocked.status == ResultStatus.BLOCKED
    assert result["app_sha256"] == asset.sha256
    assert job.status == "leased" and job.attempt_count == 1
    assert job.lease_token_hash == _digest(result["lease_token"])
    assert run.status == ExecutionStatus.RUNNING


@pytest.mark.asyncio
async def test_completion_requires_exact_pending_result_set(monkeypatch):
    runner = SimpleNamespace(id=uuid4())
    pending = SimpleNamespace(id=uuid4(), status=ResultStatus.PENDING)
    run = SimpleNamespace(results=[pending], execution_plan=None)
    db = SimpleNamespace(scalar=AsyncMock(return_value=run), commit=AsyncMock())
    monkeypatch.setattr(local_runners, "_authenticate_runner", AsyncMock(return_value=(runner, "secret")))
    monkeypatch.setattr(local_runners, "_leased_job", AsyncMock(return_value=SimpleNamespace()))
    payload = local_runners.RunnerCompleteRequest(results=[{"result_id": uuid4(), "status": "passed"}])
    with pytest.raises(HTTPException) as error:
        await local_runners.complete_job(runner.id, uuid4(), payload, db, "Bearer secret", "lease")
    assert error.value.status_code == 409
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_records_counts_and_invalidates_lease(monkeypatch):
    runner = SimpleNamespace(id=uuid4(), owner_id=uuid4())
    job = SimpleNamespace()
    pending = SimpleNamespace(id=uuid4(), status=ResultStatus.PENDING)
    blocked = SimpleNamespace(id=uuid4(), status=ResultStatus.BLOCKED)
    run = SimpleNamespace(id=uuid4(), results=[pending, blocked], execution_plan=None, project_id=uuid4(), device_name="emulator-5554", platform_version=None, target_metadata={})
    db = SimpleNamespace(scalar=AsyncMock(return_value=run), commit=AsyncMock())
    monkeypatch.setattr(local_runners, "_authenticate_runner", AsyncMock(return_value=(runner, "secret")))
    monkeypatch.setattr(local_runners, "_leased_job", AsyncMock(return_value=job))
    payload = local_runners.RunnerCompleteRequest(results=[{"result_id": pending.id, "status": "passed", "duration_ms": 12}])
    result = await local_runners.complete_job(runner.id, run.id, payload, db, "Bearer secret", "lease")
    assert result["passed"] == 1 and result["blocked"] == 1
    assert run.status == ExecutionStatus.COMPLETED and pending.duration_ms == 12
    assert job.status == "completed" and job.lease_token_hash is None and job.lease_expires_at is None
    db.commit.assert_awaited_once()
