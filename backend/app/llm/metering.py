"""Provider-neutral usage/cost metering hooks."""
import json
import logging
from dataclasses import dataclass
from typing import Callable

from app.config import Settings
from app.llm.base import LLMResponse

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


class UsageMeter:
    def __init__(self, settings: Settings, hook: UsageHook | None = None):
        try:
            self._rates = json.loads(settings.LLM_COST_RATES_JSON or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_COST_RATES_JSON must be valid JSON") from exc
        self._hook = hook

    def record(self, response: LLMResponse, tier: str) -> None:
        rate = self._rates.get(f"{response.provider}:{response.model}", {})
        input_tokens, output_tokens = response.input_tokens or 0, response.output_tokens or 0
        cost = None
        if rate:
            cost = (input_tokens * float(rate.get("input", 0)) + output_tokens * float(rate.get("output", 0))) / 1_000_000
            response.estimated_cost_usd = cost
        event = UsageEvent(response.provider, response.model, tier, input_tokens, output_tokens, cost)
        logger.info("llm_usage provider=%s model=%s tier=%s input_tokens=%s output_tokens=%s estimated_cost_usd=%s", event.provider, event.model, event.tier, event.input_tokens, event.output_tokens, event.estimated_cost_usd)
        if self._hook:
            self._hook(event)
