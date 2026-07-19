"""
LLM provider abstraction.

Every concrete provider (Azure OpenAI, OpenAI, Anthropic, Gemini, Bedrock)
implements this interface. Callers (agents, services) depend only on
`LLMProvider` - never on a concrete SDK - so a new provider can be added
without touching any calling code, and the active provider is chosen purely
through configuration (`LLM_PROVIDER` env var).
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class LLMMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)


class LLMProviderError(RuntimeError):
    """Raised when a provider call fails after retries are exhausted."""


class LLMProvider(ABC):
    """Common contract every LLM provider implementation must satisfy."""

    provider_name: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format_json: bool = False,
    ) -> LLMResponse:
        """Return a single completion for the given message list."""

    @abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Yield content chunks as they arrive, for the chat panel's streaming UI."""

    async def health_check(self) -> bool:
        """Lightweight liveness check; providers may override for a cheaper call."""
        try:
            await self.complete(
                [LLMMessage(role="user", content="ping")],
                max_tokens=1,
            )
            return True
        except Exception:
            return False
