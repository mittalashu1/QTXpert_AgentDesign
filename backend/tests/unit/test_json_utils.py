import pytest

from app.agents.test_design_agent.json_utils import LLMJsonParseError, parse_llm_json


def test_parses_clean_json():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_strips_markdown_fences():
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_salvages_json_with_preamble():
    raw = 'Here is the result:\n{"a": 1, "b": [1, 2, 3]}\nHope that helps!'
    assert parse_llm_json(raw) == {"a": 1, "b": [1, 2, 3]}


def test_raises_on_garbage():
    with pytest.raises(LLMJsonParseError):
        parse_llm_json("not json at all")
