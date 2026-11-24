from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.routes.auth import bootstrap_admin
from app.config import Settings
from app.schemas.auth import AdminBootstrap


def test_admin_bootstrap_token_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("ADMIN_BOOTSTRAP_TOKEN", "local-test-bootstrap-token")

    assert Settings().ADMIN_BOOTSTRAP_TOKEN == "local-test-bootstrap-token"


@pytest.mark.asyncio
async def test_admin_bootstrap_without_token_is_forbidden():
    settings = Settings(ADMIN_BOOTSTRAP_TOKEN=None)
    payload = AdminBootstrap(
        email="qa@example.com",
        full_name="QA Admin",
        password="local-test-password!",
        bootstrap_token="supplied-test-bootstrap-token",
    )
    request = Request({"type": "http"})
    db = AsyncMock()

    with pytest.raises(HTTPException) as exc:
        await bootstrap_admin(payload, request, db, settings)

    assert exc.value.status_code == 403
    db.execute.assert_not_awaited()
