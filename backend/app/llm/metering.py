"""Provider-neutral usage/cost metering hooks."""
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

from app.config import DEFAULT_LLM_COST_RATES_JSON, Settings
from app.llm.base import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UsageEvent:
    provider: str
    model: str
    tier: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None


UsageHook = Callable[[UsageEvent], None]


def load_cost_rates(settings: Settings) -> dict[str, dict[str, float]]:
    """Load explicit model rates for recording and legacy cost repricing."""
    try:
        raw_rates = (settings.LLM_COST_RATES_JSON or "").strip() or DEFAULT_LLM_COST_RATES_JSON
        parsed = json.loads(raw_rates)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM_COST_RATES_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("LLM_COST_RATES_JSON must be a JSON object")
    return parsed


class UsageMeter:
    def __init__(
        self,
        settings: Settings,
        hook: UsageHook | None = None,
        *,
        persist: bool = False,
    ):
        self._rates = load_cost_rates(settings)
        self._hook = hook
        self._persist = persist

    async def record(self, response: LLMResponse, tier: str) -> None:
        rate = self._rates.get(f"{response.provider}:{response.model}", {})
        input_tokens, output_tokens = response.input_tokens or 0, response.output_tokens or 0
        cost = None
        if rate:
            cost = (input_tokens * float(rate.get("input", 0)) + output_tokens * float(rate.get("output", 0))) / 1_000_000
            response.estimated_cost_usd = cost
        event = UsageEvent(response.provider, response.model, tier, input_tokens, output_tokens, cost)
        logger.info("llm_usage provider=%s model=%s tier=%s input_tokens=%s output_tokens=%s estimated_cost_usd=%s", event.provider, event.model, event.tier, event.input_tokens, event.output_tokens, event.estimated_cost_usd)
        if self._hook:
            try:
                self._hook(event)
            except Exception:  # noqa: BLE001
                logger.exception("LLM usage hook failed")
        if self._persist:
            try:
                await self._persist_event(event)
            except Exception:  # noqa: BLE001
                # Metering must never turn a successful provider response into
                # a failed user request when the database is unavailable.
                logger.exception("Could not persist LLM usage event")

    @staticmethod
    async def _persist_event(event: UsageEvent) -> None:
        # Imports stay local so lightweight provider/unit-test imports do not
        # initialize the database until persistence is explicitly enabled.
        from app.database.models.llm_usage import LLMUsageEvent
        from app.database.session import session_scope

        async with session_scope() as db:
            db.add(
                LLMUsageEvent(
                    provider=event.provider,
                    model=event.model,
                    tier=event.tier,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                    estimated_cost_usd=event.estimated_cost_usd,
                )
            )


class MeteredProvider(LLMProvider):
    """Decorates a concrete provider so direct-provider mode is metered too."""

    def __init__(self, provider: LLMProvider, meter: UsageMeter, tier: str = "direct"):
        self._provider = provider
        self._meter = meter
        self._tier = tier
        self.provider_name = provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format_json: bool = False,
    ) -> LLMResponse:
        response = await self._provider.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format_json=response_format_json,
        )
        await self._meter.record(response, self._tier)
        return response

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        # Providers currently do not expose final usage metadata for streams;
        # keep streaming behavior unchanged until the provider SDKs do.
        async for chunk in self._provider.stream(
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield chunk

