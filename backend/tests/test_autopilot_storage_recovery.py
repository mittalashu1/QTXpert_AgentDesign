import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.api.routes.autopilot import _require_owned_job
from app.config import Settings
from app.services import autopilot as autopilot_service
from app.services.autopilot import AutopilotPrototypeService, AutopilotStorageUnavailable


JOB_ID = "11111111-1111-1111-1111-111111111111"


class _FakeSession:
    def __init__(self, scalar):
        self._scalar = scalar

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def scalar(self, _statement):
        return await self._scalar()


@pytest.fixture(autouse=True)
def reset_storage_state(monkeypatch):
    monkeypatch.setattr(autopilot_service, "_PERSISTENCE_DISABLED_UNTIL", 0.0)
    with autopilot_service._DURABLE_JOB_LOADS_GUARD:
        autopilot_service._DURABLE_JOB_LOADS.clear()


def _service(tmp_path: Path) -> AutopilotPrototypeService:
    return AutopilotPrototypeService(
        Settings(AUTOPILOT_STORAGE_PATH=str(tmp_path), APP_ENV="production")
    )


@pytest.mark.asyncio
async def test_database_timeout_is_unavailable_not_job_not_found(tmp_path, monkeypatch):
    calls = 0

    async def timeout():
        nonlocal calls
        calls += 1
        raise TimeoutError("connection pool exhausted")

    monkeypatch.setattr(
        autopilot_service,
        "AsyncSessionLocal",
        lambda: _FakeSession(timeout),
    )
    service = _service(tmp_path)

    with pytest.raises(AutopilotStorageUnavailable):
        await service.load_job(JOB_ID)

    # A new service instance represents a new API request. It must respect the
    # same process-wide cooldown instead of opening another database connection.
    with pytest.raises(AutopilotStorageUnavailable):
        await _service(tmp_path).load_job(JOB_ID)
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_restore_requests_share_one_durable_read(tmp_path, monkeypatch):
    calls = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def missing_row():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return None

    monkeypatch.setattr(
        autopilot_service,
        "AsyncSessionLocal",
        lambda: _FakeSession(missing_row),
    )
    services = [_service(tmp_path), _service(tmp_path)]
    tasks = [
        asyncio.create_task(service.load_job(JOB_ID))
        for service in services
    ]
    await started.wait()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert calls == 1
    assert all(isinstance(result, FileNotFoundError) for result in results)


@pytest.mark.asyncio
async def test_real_missing_job_remains_not_found(tmp_path, monkeypatch):
    async def missing_row():
        return None

    monkeypatch.setattr(
        autopilot_service,
        "AsyncSessionLocal",
        lambda: _FakeSession(missing_row),
    )

    with pytest.raises(FileNotFoundError):
        await _service(tmp_path).load_job(JOB_ID)


@pytest.mark.asyncio
async def test_owned_job_lookup_returns_retryable_503_for_storage_outage():
    class BrokenService:
        async def load_job(self, _job_id):
            raise AutopilotStorageUnavailable("temporary")

    user = SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222"))
    with pytest.raises(HTTPException) as caught:
        await _require_owned_job(BrokenService(), JOB_ID, user)

    assert caught.value.status_code == 503
    assert "temporarily busy" in caught.value.detail


@pytest.mark.asyncio
async def test_owned_job_lookup_preserves_404_for_missing_job():
    class MissingService:
        async def load_job(self, _job_id):
            raise FileNotFoundError(JOB_ID)

    user = SimpleNamespace(id=UUID("22222222-2222-2222-2222-222222222222"))
    with pytest.raises(HTTPException) as caught:
        await _require_owned_job(MissingService(), JOB_ID, user)

    assert caught.value.status_code == 404
