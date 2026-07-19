"""Google Gemini implementation of the LLM provider interface."""
from typing import AsyncIterator, List, Optional

import google.generativeai as genai

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self, settings: Settings):
        if not settings.GOOGLE_API_KEY:
            raise LLMProviderError("GOOGLE_API_KEY must be set to use the gemini provider.")
        genai.configure(api_key=settings.GOOGLE_API_KEY)
        self._model_name = settings.LLM_MODEL
        self._settings = settings

    @staticmethod
    def _to_gemini_history(messages: List[LLMMessage]):
        system_parts = [m.content for m in messages if m.role == "system"]
        history = []
        for m in messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            history.append({"role": role, "parts": [m.content]})
        return "\n\n".join(system_parts) or None, history

    async def complete(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format_json: bool = False,
    ) -> LLMResponse:
        system_instruction, history = self._to_gemini_history(messages)
        model = genai.GenerativeModel(
            model_name=self._model_name, system_instruction=system_instruction
        )
        generation_config = {
            "temperature": temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
            "max_output_tokens": max_tokens or self._settings.LLM_MAX_TOKENS,
        }
        if response_format_json:
            generation_config["response_mime_type"] = "application/json"
        try:
            *history_msgs, last_msg = history
            chat = model.start_chat(history=history_msgs)
            response = await chat.send_message_async(
                last_msg["parts"][0], generation_config=generation_config
            )
            usage = getattr(response, "usage_metadata", None)
            return LLMResponse(
                content=response.text,
                model=self._model_name,
                provider=self.provider_name,
                input_tokens=getattr(usage, "prompt_token_count", None),
                output_tokens=getattr(usage, "candidates_token_count", None),
                raw={"text": response.text},
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Gemini completion failed: {exc}") from exc

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        system_instruction, history = self._to_gemini_history(messages)
        model = genai.GenerativeModel(
            model_name=self._model_name, system_instruction=system_instruction
        )
        generation_config = {
            "temperature": temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
            "max_output_tokens": max_tokens or self._settings.LLM_MAX_TOKENS,
        }
        try:
            *history_msgs, last_msg = history
            chat = model.start_chat(history=history_msgs)
            response = await chat.send_message_async(
                last_msg["parts"][0], generation_config=generation_config, stream=True
            )
            async for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Gemini streaming failed: {exc}") from exc
