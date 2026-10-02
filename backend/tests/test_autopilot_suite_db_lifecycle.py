import pytest

from app.api.routes.autopilot import _run_suite_without_db_connection


class _SessionStub:
    def __init__(self):
        self.connection_checked_out = True
        self.rollback_calls = 0

    async def rollback(self):
        self.rollback_calls += 1
        self.connection_checked_out = False


@pytest.mark.asyncio
async def test_remote_suite_runs_only_after_request_db_transaction_is_released():
    db = _SessionStub()

    async def remote_run(job_id, *, batch_size):
        assert db.connection_checked_out is False
        assert job_id == "job-123"
        assert batch_size == 20
        return "suite-result"

    result = await _run_suite_without_db_connection(
        db,
        remote_run,
        "job-123",
        batch_size=20,
    )

    assert result == "suite-result"
    assert db.rollback_calls == 1
