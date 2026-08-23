import pytest
from pydantic import ValidationError

from app.config import Settings
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


def test_llm_request_timeout_has_safe_default(monkeypatch):
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT_SECONDS", raising=False)
    assert Settings().LLM_REQUEST_TIMEOUT_SECONDS == 75


def test_llm_request_timeout_can_be_configured(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "120")
    assert Settings().LLM_REQUEST_TIMEOUT_SECONDS == 120


def test_llm_request_timeout_rejects_unsafe_values(monkeypatch):
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "0")
    with pytest.raises(ValidationError):
        Settings()
