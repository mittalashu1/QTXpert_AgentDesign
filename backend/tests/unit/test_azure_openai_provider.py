from app.llm.providers.azure_openai_provider import _is_reasoning_deployment


def test_reasoning_deployment_detection_is_explicit():
    assert _is_reasoning_deployment("gpt-5.6-terra")
    assert _is_reasoning_deployment("o3-mini")
    assert not _is_reasoning_deployment("gpt-4o")
    assert not _is_reasoning_deployment("custom-gpt5-wrapper")
