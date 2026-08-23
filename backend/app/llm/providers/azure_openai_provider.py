"""Azure OpenAI implementation of the LLM provider interface (default provider)."""
import logging
from typing import AsyncIterator, List, Optional

from openai import AsyncAzureOpenAI

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse
logger = logging.getLogger(__name__)


def _is_reasoning_deployment(name: str) -> bool:
    """Use the Chat Completions parameter set supported by reasoning models."""
    normalized = name.lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


class AzureOpenAIProvider(LLMProvider):
    provider_name = "azure_openai"

    def __init__(self, settings: Settings):
        if not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_ENDPOINT:
            raise LLMProviderError(
                "AZURE_OPENAI_API_KEY and AZURE_ENDPOINT must be set to use the "
                "azure_openai provider."
            )
        self._client = AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            azure_endpoint=settings.AZURE_ENDPOINT,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
        self._deployment = settings.AZURE_OPENAI_DEPLOYMENT or settings.LLM_MODEL
        self._settings = settings

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format_json: bool = False,
    ) -> LLMResponse:
        try:
            reasoning = _is_reasoning_deployment(self._deployment)
            request = {
                "model": self._deployment,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "timeout": self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            }
            if reasoning:
                request["max_completion_tokens"] = max_tokens or self._settings.LLM_MAX_TOKENS
                request["reasoning_effort"] = self._settings.LLM_REASONING_EFFORT
            else:
                request["max_tokens"] = max_tokens or self._settings.LLM_MAX_TOKENS
                request["temperature"] = (
                    temperature if temperature is not None else self._settings.LLM_TEMPERATURE
                )
            if response_format_json:
                request["response_format"] = {"type": "json_object"}
            response = await self._client.chat.completions.create(**request)
            if not response.choices:
                raise LLMProviderError("Azure OpenAI returned no choices")
            choice = response.choices[0]
            if getattr(choice.message, "refusal", None):
                raise LLMProviderError(
                    f"Azure OpenAI refused the structured request: {choice.message.refusal}"
                )
            if not choice.message.content:
                logger.warning(
                    "Azure completion contained no visible content: deployment=%s finish_reason=%s refusal=%s usage=%s",
                    self._deployment,
                    choice.finish_reason,
                    getattr(choice.message, "refusal", None),
                    response.usage.model_dump() if response.usage else None,
                )
            return LLMResponse(
                content=choice.message.content or "",
                model=self._deployment,
                provider=self.provider_name,
                input_tokens=response.usage.prompt_tokens if response.usage else None,
                output_tokens=response.usage.completion_tokens if response.usage else None,
                raw=response.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Azure OpenAI completion failed: {exc}") from exc

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                **(
                    {}
                    if self._deployment.startswith(("gpt-5", "o1", "o3", "o4"))
                    else {
                        "temperature": (
                            temperature if temperature is not None else self._settings.LLM_TEMPERATURE
                        )
                    }
                ),
                max_completion_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                stream=True,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Azure OpenAI streaming failed: {exc}") from exc
