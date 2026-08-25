"""Cost-first model router with cross-provider fallback and escalation."""
import logging
from typing import AsyncIterator, Callable, List, Optional

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse
from app.llm.metering import UsageMeter

logger = logging.getLogger(__name__)


class ModelRouter(LLMProvider):
    provider_name = "router"

    def __init__(self, settings: Settings, provider_factory: Callable[[str, str], LLMProvider], meter: UsageMeter | None = None):
        self._settings, self._provider_factory = settings, provider_factory
        self._meter = meter or UsageMeter(settings)
        self._tiers = {
            "low": self._parse(settings.LLM_ROUTER_LOW_COST),
            "standard": self._parse(settings.LLM_ROUTER_STANDARD),
            "complex": self._parse(settings.LLM_ROUTER_COMPLEX),
        }
        self._fallback = self._parse(settings.LLM_ROUTER_FALLBACK)

    @staticmethod
    def _parse(value: str) -> list[tuple[str, str]]:
        targets = []
        for item in value.split(","):
            item = item.strip()
            if item:
                provider, sep, model = item.partition(":")
                if not sep or not provider or not model:
                    raise LLMProviderError(f"Invalid router target '{item}'; expected provider:model")
                targets.append((provider, model))
        return targets

    @property
    def model_name(self) -> str:
        return "cost-first"

    def _tier(self, messages: List[LLMMessage]) -> str:
        text = " ".join(message.content for message in messages).lower()
        if len(text) >= self._settings.LLM_ROUTER_COMPLEX_INPUT_CHARS or any(term in text for term in ("regulatory", "root cause", "automation script", "complex uat")):
            return "complex"
        if any(term in text for term in ("risk analysis", "test scenario", "functional breakdown", "detailed test case")):
            return "standard"
        return "low"

    def _route(self, tier: str):
        order = ["low", "standard", "complex"]
        start = order.index(tier)
        seen = set()
        for name in order[start:]:
            for target in self._tiers[name]:
                if target not in seen:
                    seen.add(target)
                    yield name, target
        for target in self._fallback:
            if target not in seen:
                yield "fallback", target

    async def complete(self, messages: List[LLMMessage], *, temperature: Optional[float] = None, max_tokens: Optional[int] = None, response_format_json: bool = False) -> LLMResponse:
        tier, errors = self._tier(messages), []
        for attempted_tier, (provider_name, model) in self._route(tier):
            try:
                provider = self._provider_factory(provider_name, model)
                response = await provider.complete(messages, temperature=temperature, max_tokens=max_tokens, response_format_json=response_format_json)
                if not response.content.strip():
                    raise LLMProviderError("provider returned an empty response")
                await self._meter.record(response, attempted_tier)
                return response
            except LLMProviderError as exc:
                errors.append(f"{provider_name}:{model}: {exc}")
                logger.warning("llm_route_failed tier=%s provider=%s model=%s error=%s", attempted_tier, provider_name, model, exc)
        raise LLMProviderError("All configured model routes failed: " + " | ".join(errors))

    async def stream(self, messages: List[LLMMessage], *, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> AsyncIterator[str]:
        # Streaming cannot safely switch after bytes have reached a client. We
        # can fall back only when a provider fails before yielding its first chunk.
        tier, errors = self._tier(messages), []
        for attempted_tier, (provider_name, model) in self._route(tier):
            yielded = False
            try:
                provider = self._provider_factory(provider_name, model)
                async for chunk in provider.stream(messages, temperature=temperature, max_tokens=max_tokens):
                    yielded = True
                    yield chunk
                return
            except LLMProviderError as exc:
                if yielded:
                    raise
                errors.append(f"{provider_name}:{model}: {exc}")
                logger.warning("llm_stream_route_failed tier=%s provider=%s model=%s", attempted_tier, provider_name, model)
        raise LLMProviderError("All configured streaming routes failed: " + " | ".join(errors))
