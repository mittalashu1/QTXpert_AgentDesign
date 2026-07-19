"""Anthropic Claude implementation of the LLM provider interface."""
from typing import AsyncIterator, List, Optional

from anthropic import AsyncAnthropic

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse


class AnthropicProvider(LLMProvider):
    provider_name = "anthropic"

    def __init__(self, settings: Settings):
        if not settings.ANTHROPIC_API_KEY:
            raise LLMProviderError(
                "ANTHROPIC_API_KEY must be set to use the anthropic provider."
            )
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.LLM_MODEL
        self._settings = settings

    @staticmethod
    def _split_system(messages: List[LLMMessage]):
        system_parts = [m.content for m in messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": m.content} for m in messages if m.role != "system"
        ]
        return "\n\n".join(system_parts) or None, conversation

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format_json: bool = False,
    ) -> LLMResponse:
        system, conversation = self._split_system(messages)
        try:
            response = await self._client.messages.create(
                model=self._model,
                system=system,
                messages=conversation,
                temperature=temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            content = "".join(block.text for block in response.content if block.type == "text")
            return LLMResponse(
                content=content,
                model=self._model,
                provider=self.provider_name,
                input_tokens=response.usage.input_tokens if response.usage else None,
                output_tokens=response.usage.output_tokens if response.usage else None,
                raw=response.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Anthropic completion failed: {exc}") from exc

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        system, conversation = self._split_system(messages)
        try:
            async with self._client.messages.stream(
                model=self._model,
                system=system,
                messages=conversation,
                temperature=temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Anthropic streaming failed: {exc}") from exc
