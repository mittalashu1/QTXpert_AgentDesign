"""
Node functions for the Test Design Agent LangGraph workflow.

Each node: (1) builds a prompt, (2) calls the configured LLM provider,
(3) parses the JSON response, (4) merges results into state. Nodes never
import a concrete LLM SDK - only `app.llm.base.LLMProvider`.
"""
import asyncio
import logging
from typing import Any, Dict

from app.agents.test_design_agent.json_utils import LLMJsonParseError, parse_llm_json
from app.config import get_settings
from app.agents.test_design_agent.state import TestDesignState
from app.llm.base import LLMMessage, LLMProvider, LLMProviderError
from app.prompts import test_design_prompts as prompts

logger = logging.getLogger(__name__)


async def _call_json(
    provider: LLMProvider, system: str, user: str, timeout_seconds: float | None = None,
    max_retries: int | None = None, max_tokens: int | None = None,
) -> Dict[str, Any]:
    """Request machine-readable output, retrying transient empty/model-formatted replies."""
    retry_system = system + (
        " Your response must be a non-empty JSON object only. Do not use markdown,"
        " explanations, or an empty response."
    )
    settings = get_settings()
    timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.LLM_REQUEST_TIMEOUT_SECONDS
    attempts = (max_retries if max_retries is not None else settings.LLM_MAX_RETRIES) + 1
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            response = await asyncio.wait_for(
                provider.complete(
                    [
                        LLMMessage(role="system", content=retry_system if attempt else system),
                        LLMMessage(role="user", content=user),
                    ],
                    # Some reasoning-model deployments return whitespace in legacy
                    # JSON mode. The retry relies on the explicit prompt instead.
                    response_format_json=attempt == 0,
                    max_tokens=max_tokens,
                ),
                timeout=timeout_seconds,
            )
            parsed = parse_llm_json(response.content)
            if not isinstance(parsed, dict):
                raise LLMJsonParseError("LLM response must be a JSON object")
            return parsed
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning("LLM request timed out on attempt %s after %ss", attempt + 1, timeout_seconds)
        except LLMJsonParseError as exc:
            last_error = exc
            logger.warning("LLM returned unusable JSON on attempt %s: %s", attempt + 1, exc)
        except LLMProviderError as exc:
            last_error = exc
            logger.warning("LLM provider failed on attempt %s: %s", attempt + 1, exc)
            if attempt + 1 < max(1, attempts):
                await asyncio.sleep(min(2 ** attempt, 4))
    if isinstance(last_error, asyncio.TimeoutError):
        raise LLMProviderError(
            "The AI did not respond in time. Please start the generation again."
        ) from last_error
    raise LLMProviderError(
        "The AI returned an empty or invalid structured response after retries. "
        "Please try the generation again."
    ) from last_error


def make_normalize_node(provider: LLMProvider):
    async def normalize_node(state: TestDesignState) -> TestDesignState:
        system, user = prompts.normalize_requirements_prompt(state["raw_documents"])
        result = await _call_json(provider, system, user)
        state["normalized_text"] = result.get("normalized_text", "")
        return state

    return normalize_node


def make_extract_structure_node(provider: LLMProvider):
    async def extract_structure_node(state: TestDesignState) -> TestDesignState:
        system, user = prompts.extract_structure_prompt(state["normalized_text"])
        result = await _call_json(provider, system, user)
        state["structure"] = result
        return state

    return extract_structure_node


def make_summary_node(provider: LLMProvider):
    async def summary_node(state: TestDesignState) -> TestDesignState:
        system, user = prompts.requirement_summary_prompt(state["normalized_text"])
        result = await _call_json(provider, system, user)
        state["requirement_summary"] = result.get("summary", "")
        return state

    return summary_node


def make_functional_breakdown_node(provider: LLMProvider):
    async def functional_breakdown_node(state: TestDesignState) -> TestDesignState:
        system, user = prompts.functional_breakdown_prompt(
            state["normalized_text"], state["structure"]
        )
        result = await _call_json(provider, system, user)
        state["functional_breakdown"] = result.get("functional_breakdown", [])
        return state

    return functional_breakdown_node


def make_test_scenarios_node(provider: LLMProvider):
    async def test_scenarios_node(state: TestDesignState) -> TestDesignState:
        system, user = prompts.test_scenarios_prompt(state["functional_breakdown"])
        result = await _call_json(provider, system, user)
        state["test_scenarios"] = result.get("test_scenarios", [])
        return state

    return test_scenarios_node


def make_detailed_test_cases_node(provider: LLMProvider, on_test_case_batch=None, max_scenarios: int = 40):
    async def detailed_test_cases_node(state: TestDesignState) -> TestDesignState:
        all_cases = []
        # A single requirement often produces many scenarios. Generate a few
        # at once so the first completed group can be shown to the user rather
        # than making them wait for every scenario to run serially.
        semaphore = asyncio.Semaphore(3)
        # LangGraph runs scenario tasks concurrently, but the persistence
        # callback uses one AsyncSession. Serialize callback execution so
        # concurrent scenario completions cannot overlap DB transactions.
        persist_lock = asyncio.Lock()

        async def generate_for_scenario(scenario):
            system, user = prompts.detailed_test_cases_prompt(scenario, state["structure"])
            try:
                async with semaphore:
                    result = await _call_json(provider, system, user, timeout_seconds=20, max_retries=0)
            except Exception as exc:  # noqa: BLE001
                title = str(scenario.get("title") or scenario.get("scenario_id") or "Generated scenario")
                fallback = {
                    "scenario": title,
                    "objective": f"Validate the expected behavior for: {title}",
                    "preconditions": "Application is available and required test data is prepared.",
                    "steps": [{"step": 1, "action": f"Execute the workflow described by: {title}"}],
                    "expected_result": f"The workflow for '{title}' completes according to the requirement.",
                    "test_type": "functional", "priority": "medium", "severity": "minor",
                    "risk_level": "medium", "is_automation_candidate": False,
                }
                return scenario, [fallback], exc
            return scenario, result.get("test_cases", []), None

        scenarios = state["test_scenarios"][:max_scenarios]
        skipped_scenarios = len(state["test_scenarios"]) - len(scenarios)
        if skipped_scenarios:
            state.setdefault("errors", []).append(
                f"Skipped {skipped_scenarios} scenarios because the generation limit is {max_scenarios}."
            )
        tasks = [asyncio.create_task(generate_for_scenario(s)) for s in scenarios]
        for task in asyncio.as_completed(tasks):
            scenario, cases, error = await task
            if error:
                logger.warning("Test case generation failed for scenario %s: %s", scenario, error)
                state.setdefault("errors", []).append(
                    f"Scenario '{scenario.get('title', scenario.get('scenario_id'))}' failed: {error}"
                )
                # Keep the generated suite useful even when a detail call times
                # out: generate_for_scenario returns an input-specific fallback.
                # Do not discard it just because the provider call failed.
            for case in cases:
                case["scenario_id"] = scenario.get("scenario_id")
                all_cases.append(case)
            if on_test_case_batch:
                async with persist_lock:
                    await on_test_case_batch(cases)
        state["test_cases"] = all_cases
        state["automation_candidate_count"] = sum(
            1 for c in all_cases if c.get("is_automation_candidate")
        )
        return state

    return detailed_test_cases_node


def make_risk_analysis_node(provider: LLMProvider):
    async def risk_analysis_node(state: TestDesignState) -> TestDesignState:
        summary = {
            "total_test_cases": len(state.get("test_cases", [])),
            "automation_candidates": state.get("automation_candidate_count", 0),
            "test_type_distribution": _distribution(state.get("test_cases", []), "test_type"),
            "priority_distribution": _distribution(state.get("test_cases", []), "priority"),
        }
        system, user = prompts.risk_analysis_prompt(state["structure"], summary)
        result = await _call_json(provider, system, user)
        state["risk_analysis"] = result
        return state

    return risk_analysis_node


def _distribution(items: list, key: str) -> Dict[str, int]:
    dist: Dict[str, int] = {}
    for item in items:
        value = item.get(key, "unknown")
        dist[value] = dist.get(value, 0) + 1
    return dist

