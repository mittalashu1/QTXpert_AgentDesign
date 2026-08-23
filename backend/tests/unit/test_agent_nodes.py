import asyncio

import pytest

from app.agents.test_design_agent.nodes import _call_json
from app.llm.base import LLMProvider, LLMResponse


class EmptyThenJsonProvider(LLMProvider):
    provider_name = "test"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return LLMResponse(content="" if self.calls == 1 else '{"ok": true}', model="test", provider="test")

    async def stream(self, messages, **kwargs):
        yield ""


@pytest.mark.asyncio
async def test_call_json_retries_an_empty_completion():
    provider = EmptyThenJsonProvider()
    assert await _call_json(provider, "Return JSON", "input") == {"ok": True}
    assert provider.calls == 2



class HangingProvider(LLMProvider):
    provider_name = "test"

    async def complete(self, messages, **kwargs):
        await asyncio.sleep(1)

    async def stream(self, messages, **kwargs):
        yield ""


@pytest.mark.asyncio
async def test_call_json_fails_after_retrying_a_timeout():
    with pytest.raises(Exception, match="did not respond in time"):
        await _call_json(HangingProvider(), "Return JSON", "input", timeout_seconds=0.001)


class TransientProvider(LLMProvider):
    provider_name = "test"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            from app.llm.base import LLMProviderError
            raise LLMProviderError("temporary upstream failure")
        return LLMResponse(content='{"ok": true}', model="test", provider="test")

    async def stream(self, messages, **kwargs):
        yield ""


@pytest.mark.asyncio
async def test_call_json_retries_transient_provider_failure():
    provider = TransientProvider()
    assert await _call_json(provider, "Return JSON", "input", timeout_seconds=1) == {"ok": True}
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_call_json_rejects_non_object_json():
    class ArrayProvider(LLMProvider):
        provider_name = "test"

        async def complete(self, messages, **kwargs):
            return LLMResponse(content='[]', model="test", provider="test")

        async def stream(self, messages, **kwargs):
            yield ""

    with pytest.raises(Exception, match="invalid structured response"):
        await _call_json(ArrayProvider(), "Return JSON", "input", timeout_seconds=1, max_retries=0)
