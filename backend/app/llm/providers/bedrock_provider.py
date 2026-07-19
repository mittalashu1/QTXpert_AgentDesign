"""AWS Bedrock implementation of the LLM provider interface (Claude on Bedrock)."""
import json
from typing import AsyncIterator, List, Optional

import aioboto3

from app.config import Settings
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError, LLMResponse


class BedrockProvider(LLMProvider):
    provider_name = "bedrock"

    def __init__(self, settings: Settings):
        if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
            raise LLMProviderError(
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set to use the "
                "bedrock provider."
            )
        self._session = aioboto3.Session(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        self._model_id = settings.BEDROCK_MODEL_ID
        self._settings = settings

    @staticmethod
    def _split_system(messages: List[LLMMessage]):
        system_parts = [m.content for m in messages if m.role == "system"]
        conversation = [
            {"role": m.role, "content": [{"type": "text", "text": m.content}]}
            for m in messages
            if m.role != "system"
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
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system,
            "messages": conversation,
            "temperature": temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or self._settings.LLM_MAX_TOKENS,
        }
        try:
            async with self._session.client("bedrock-runtime") as client:
                response = await client.invoke_model(
                    modelId=self._model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                payload = json.loads(await response["body"].read())
                content = "".join(
                    block["text"] for block in payload.get("content", []) if block.get("type") == "text"
                )
                usage = payload.get("usage", {})
                return LLMResponse(
                    content=content,
                    model=self._model_id,
                    provider=self.provider_name,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    raw=payload,
                )
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Bedrock completion failed: {exc}") from exc

    async def stream(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        system, conversation = self._split_system(messages)
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "system": system,
            "messages": conversation,
            "temperature": temperature if temperature is not None else self._settings.LLM_TEMPERATURE,
            "max_tokens": max_tokens or self._settings.LLM_MAX_TOKENS,
        }
        try:
            async with self._session.client("bedrock-runtime") as client:
                response = await client.invoke_model_with_response_stream(
                    modelId=self._model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                async for event in response["body"]:
                    chunk = json.loads(event["chunk"]["bytes"])
                    if chunk.get("type") == "content_block_delta":
                        delta = chunk.get("delta", {})
                        if delta.get("type") == "text_delta":
                            yield delta.get("text", "")
        except Exception as exc:  # noqa: BLE001
            raise LLMProviderError(f"Bedrock streaming failed: {exc}") from exc
