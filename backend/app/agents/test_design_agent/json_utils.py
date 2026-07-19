"""Robust JSON extraction from LLM completions.

LLMs occasionally wrap JSON in markdown fences or add stray whitespace even
when instructed not to; this helper defends against that without silently
swallowing genuine malformed output.
"""
import json
import re
from typing import Any


class LLMJsonParseError(ValueError):
    pass


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_llm_json(raw_content: str) -> Any:
    cleaned = _FENCE_RE.sub("", raw_content.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Attempt to salvage by trimming to the outermost JSON object/array
        start_candidates = [i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1]
        if not start_candidates:
            raise LLMJsonParseError(
                f"LLM response was not valid JSON: {exc}. Raw: {cleaned[:500]}"
            ) from exc
        start = min(start_candidates)
        end = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if end <= start:
            raise LLMJsonParseError(
                f"LLM response was not valid JSON: {exc}. Raw: {cleaned[:500]}"
            ) from exc
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as inner_exc:
            raise LLMJsonParseError(
                f"LLM response was not valid JSON after salvage attempt: {inner_exc}. "
                f"Raw: {cleaned[:500]}"
            ) from inner_exc
