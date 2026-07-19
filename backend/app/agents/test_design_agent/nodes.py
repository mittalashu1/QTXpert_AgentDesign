"""
Node functions for the Test Design Agent LangGraph workflow.

Each node: (1) builds a prompt, (2) calls the configured LLM provider,
(3) parses the JSON response, (4) merges results into state. Nodes never
import a concrete LLM SDK - only `app.llm.base.LLMProvider`.
"""
import logging
from typing import Any, Dict

from app.agents.test_design_agent.json_utils import parse_llm_json
from app.agents.test_design_agent.state import TestDesignState
from app.llm.base import LLMMessage, LLMProvider
from app.prompts import test_design_prompts as prompts

logger = logging.getLogger(__name__)


async def _call_json(provider: LLMProvider, system: str, user: str) -> Dict[str, Any]:
    response = await provider.complete(
        [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)],
        response_format_json=True,
    )
    return parse_llm_json(response.content)


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


def make_detailed_test_cases_node(provider: LLMProvider):
    async def detailed_test_cases_node(state: TestDesignState) -> TestDesignState:
        all_cases = []
        for scenario in state["test_scenarios"]:
            system, user = prompts.detailed_test_cases_prompt(scenario, state["structure"])
            try:
                result = await _call_json(provider, system, user)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Test case generation failed for scenario %s: %s", scenario, exc)
                state.setdefault("errors", []).append(
                    f"Scenario '{scenario.get('title', scenario.get('scenario_id'))}' failed: {exc}"
                )
                continue
            for case in result.get("test_cases", []):
                case["scenario_id"] = scenario.get("scenario_id")
                all_cases.append(case)
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
