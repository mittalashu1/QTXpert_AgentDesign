"""
Factory that resolves the active `LLMProvider` implementation from config.

This is the single place in the codebase that knows about concrete provider
classes. Everything else (agents, services, API routes) depends only on
`app.llm.base.LLMProvider`.
"""
from functools import lru_cache
from typing import Callable, Dict

from app.config import Settings, get_settings
from app.llm.base import LLMProvider, LLMProviderError

_REGISTRY: Dict[str, Callable[[Settings], LLMProvider]] = {}


def register_provider(name: str, factory: Callable[[Settings], LLMProvider]) -> None:
    """Registers a provider factory under a configuration key.

    Kept as a public function (rather than a hardcoded dict literal) so a
    future agent module can register an additional provider without editing
    this file.
    """
    _REGISTRY[name] = factory


def _register_builtin_providers() -> None:
    from app.llm.providers.azure_openai_provider import AzureOpenAIProvider
    from app.llm.providers.openai_provider import OpenAIProvider
    from app.llm.providers.anthropic_provider import AnthropicProvider
    from app.llm.providers.gemini_provider import GeminiProvider
    from app.llm.providers.bedrock_provider import BedrockProvider

    register_provider("azure_openai", AzureOpenAIProvider)
    register_provider("openai", OpenAIProvider)
    register_provider("anthropic", AnthropicProvider)
    register_provider("gemini", GeminiProvider)
    register_provider("bedrock", BedrockProvider)


_register_builtin_providers()


@lru_cache
def get_llm_provider(provider_override: str | None = None) -> LLMProvider:
    """Returns the configured LLM provider instance (cached per process).

    Args:
        provider_override: if given, bypasses `settings.LLM_PROVIDER` - used
            by the Settings page / API config endpoint to test a provider
            before saving it as the default.
    """
    settings = get_settings()
    provider_key = provider_override or settings.LLM_PROVIDER
    factory = _REGISTRY.get(provider_key)
    if factory is None:
        raise LLMProviderError(
            f"Unknown LLM provider '{provider_key}'. Registered providers: "
            f"{list(_REGISTRY.keys())}"
        )
    return factory(settings)
