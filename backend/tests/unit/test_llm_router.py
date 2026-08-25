import pytest

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse
from app.llm.metering import UsageMeter
from app.llm.router import ModelRouter


class StubProvider(LLMProvider):
    def __init__(self, provider, model, fail=False):
        self.provider_name, self._model, self.fail = provider, model, fail

    async def complete(self, messages, **kwargs):
        if self.fail:
            raise LLMProviderError("unavailable")
        return LLMResponse("{}", self._model, self.provider_name, 100, 50)

    async def stream(self, messages, **kwargs):
        if self.fail:
            raise LLMProviderError("unavailable")
        yield "ok"


def settings(**updates):
    values = dict(
        LLM_ROUTER_LOW_COST="gemini:cheap",
        LLM_ROUTER_STANDARD="openai:standard",
        LLM_ROUTER_COMPLEX="azure_openai:strong",
        LLM_ROUTER_FALLBACK="openai:fallback",
    )
    values.update(updates)
    return Settings(**values)


@pytest.mark.asyncio
async def test_simple_request_uses_low_cost_route():
    calls = []
    def factory(provider, model):
        calls.append((provider, model))
        return StubProvider(provider, model)
    response = await ModelRouter(settings(), factory).complete([LLMMessage("user", "classify this")])
    assert (response.provider, response.model) == ("gemini", "cheap")
    assert calls == [("gemini", "cheap")]


@pytest.mark.asyncio
async def test_failure_escalates_to_next_tier():
    calls = []
    def factory(provider, model):
        calls.append((provider, model))
        return StubProvider(provider, model, fail=model == "cheap")
    response = await ModelRouter(settings(), factory).complete([LLMMessage("user", "classify this")])
    assert response.model == "standard"
    assert calls == [("gemini", "cheap"), ("openai", "standard")]


@pytest.mark.asyncio
async def test_complex_prompt_starts_on_complex_route():
    calls = []
    def factory(provider, model):
        calls.append((provider, model))
        return StubProvider(provider, model)
    await ModelRouter(settings(), factory).complete([LLMMessage("user", "perform complex UAT regulatory analysis")])
    assert calls == [("azure_openai", "strong")]


@pytest.mark.asyncio
async def test_meter_estimates_cost_and_emits_hook():
    events = []
    configured = settings(LLM_COST_RATES_JSON='{"gemini:cheap":{"input":1,"output":2}}')
    router = ModelRouter(configured, lambda p, m: StubProvider(p, m), UsageMeter(configured, events.append))
    response = await router.complete([LLMMessage("user", "short")])
    assert response.estimated_cost_usd == pytest.approx(0.0002)
    assert events[0].tier == "low"
