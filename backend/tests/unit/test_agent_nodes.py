import pytest

from app.agents.test_design_agent.nodes import _call_json
from app.llm.base import LLMProvider, LLMResponse


class EmptyThenJsonProvider(LLMProvider):
    provider_name = "test"

    def __init__(self):
        self.calls = 0
        self.json_modes = []

    async def complete(self, messages, **kwargs):
        self.calls += 1
        self.json_modes.append(kwargs["response_format_json"])
        return LLMResponse(content="" if self.calls == 1 else '{"ok": true}', model="test", provider="test")

    async def stream(self, messages, **kwargs):
        yield ""


@pytest.mark.asyncio
async def test_call_json_retries_an_empty_completion():
    provider = EmptyThenJsonProvider()
    assert await _call_json(provider, "Return JSON", "input") == {"ok": True}
    assert provider.calls == 2
    assert provider.json_modes == [True, False]

