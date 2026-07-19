"""Public OpenAI implementation of the LLM provider interface."""
from typing import AsyncIterator, List, Optional

from openai import AsyncOpenAI

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse


class OpenAIProvider(LLMProvider):
    provider_name = "openai"

    def __init__(self, settings: Settings):
        if not settings.OPENAI_API_KEY:
            raise LLMProviderError("OPENAI_API_KEY must be set to use the openai provider.")
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._model = settings.LLM_MODEL
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
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                response_format={"type": "json_object"} if response_format_json else None,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            choice = response.choices[0]
            return LLMResponse(
                content=choice.message.content or "",
                model=self._model,
                provider=self.provider_name,
                input_tokens=response.usage.prompt_tokens if response.usage else None,
                output_tokens=response.usage.completion_tokens if response.usage else None,
                raw=response.model_dump(),
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"OpenAI completion failed: {exc}") from exc

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                temperature=temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
                max_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                stream=True,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"OpenAI streaming failed: {exc}") from exc
