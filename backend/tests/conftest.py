import os

os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://qtxpert:qtxpert@localhost:5432/qtxpert_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-pytest-only")

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
