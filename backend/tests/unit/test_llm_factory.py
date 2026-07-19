import pytest

from app.llm.base import LLMProviderError
from app.llm.factory import get_llm_provider


def test_unknown_provider_raises():
    get_llm_provider.cache_clear()
    with pytest.raises(LLMProviderError):
        get_llm_provider("not_a_real_provider")


def test_provider_without_credentials_raises_configuration_error(monkeypatch):
    get_llm_provider.cache_clear()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(LLMProviderError):
        get_llm_provider("openai")
