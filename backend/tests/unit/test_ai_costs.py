import pytest

from app.config import Settings
from app.llm.base import LLMResponse
from app.llm.metering import UsageMeter


@pytest.mark.asyncio
async def test_usage_meter_persists_a_priced_event(monkeypatch):
    settings = Settings(
        LLM_COST_RATES_JSON='{"gemini:cheap":{"input":1,"output":2}}'
    )
    persisted = []

    async def capture(event):
        persisted.append(event)

    monkeypatch.setattr(UsageMeter, "_persist_event", staticmethod(capture))
    meter = UsageMeter(settings, persist=True)
    response = LLMResponse("{}", "cheap", "gemini", 100, 50)

    await meter.record(response, "low")

    assert response.estimated_cost_usd == pytest.approx(0.0002)
    assert persisted[0].provider == "gemini"
    assert persisted[0].tier == "low"


@pytest.mark.asyncio
async def test_admin_cost_endpoint_requires_admin_auth(client):
    response = await client.get("/api/v1/admin/ai-costs")

    assert response.status_code == 401
