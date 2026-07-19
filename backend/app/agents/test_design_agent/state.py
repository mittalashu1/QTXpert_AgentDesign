"""Typed state passed between LangGraph nodes for the Test Design Agent."""
from typing import Any, Dict, List, TypedDict


class TestDesignState(TypedDict, total=False):
    # Inputs
    raw_documents: List[str]
    project_id: str
    generation_run_id: str

    # Step 2-4 outputs
    normalized_text: str
    structure: Dict[str, Any]

    # Step 5-7 outputs
    requirement_summary: str
    functional_breakdown: List[Dict[str, Any]]

    # Step 8 output
    test_scenarios: List[Dict[str, Any]]

    # Step 9 output
    test_cases: List[Dict[str, Any]]

    # Step 10 - automation candidates are flagged inline on each test case
    automation_candidate_count: int

    # Step 11 output
    risk_analysis: Dict[str, Any]

    # Bookkeeping
    errors: List[str]
    llm_provider: str
    llm_model: str
