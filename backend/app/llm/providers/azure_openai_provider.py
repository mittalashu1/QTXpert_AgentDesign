"""Azure OpenAI implementation of the LLM provider interface (default provider)."""
import logging
from typing import AsyncIterator, List, Optional

from openai import AsyncAzureOpenAI

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse

logger = logging.getLogger(__name__)


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
            options = {}
            if self._deployment.startswith(("gpt-5", "o1", "o3", "o4")):
                # Preserve visible output tokens for structured test artifacts.
                options["reasoning_effort"] = self._settings.LLM_REASONING_EFFORT
            else:
                options["temperature"] = temperature if temperature is not None else self._settings.LLM_TEMPERATURE
            response = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                # GPT-5-series reasoning-tuned models only accept the default
                # temperature (1) and reject any other explicit value, unlike
                # GPT-4o-era models. Only send temperature for models that
                # support tuning it.
                **options,
                # GPT-5-series models require max_completion_tokens instead
                # of the legacy max_tokens parameter.
                max_completion_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                response_format={"type": "json_object"} if response_format_json else None,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            choice = response.choices[0]
            content = choice.message.content or ""
            if not content.strip():
                logger.warning(
                    "Azure completion was empty (deployment=%s, finish_reason=%s, refusal=%s, usage=%s)",
                    self._deployment, choice.finish_reason, getattr(choice.message, "refusal", None),
                    response.usage.model_dump() if response.usage else None,
                )
            return LLMResponse(
                content=content,
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
            options = {}
            if self._deployment.startswith(("gpt-5", "o1", "o3", "o4")):
                options["reasoning_effort"] = self._settings.LLM_REASONING_EFFORT
            else:
                options["temperature"] = temperature if temperature is not None else self._settings.LLM_TEMPERATURE
            stream = await self._client.chat.completions.create(
                model=self._deployment,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                **options,
                max_completion_tokens=max_tokens or self._settings.LLM_MAX_TOKENS,
                stream=True,
                timeout=self._settings.LLM_REQUEST_TIMEOUT_SECONDS,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Azure OpenAI streaming failed: {exc}") from exc

