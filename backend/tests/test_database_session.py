import pytest

from app.database import session as database_session


@pytest.mark.asyncio
async def test_safe_close_invalidates_a_connection_when_close_times_out(monkeypatch):
    invalidated = []

    class FakeSyncSession:
        def invalidate(self):
            invalidated.append(True)

    class FakeSession:
        sync_session = FakeSyncSession()

        async def close(self):
            raise TimeoutError("connection close timed out")

    monkeypatch.setattr(database_session.settings, "DB_CLOSE_TIMEOUT_SECONDS", 1)

    await database_session._safe_close(FakeSession())

    assert invalidated == [True]
