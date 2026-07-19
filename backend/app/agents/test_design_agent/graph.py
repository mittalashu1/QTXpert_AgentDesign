"""
LangGraph StateGraph implementing steps 2-11 of the AI workflow:
normalize -> extract structure -> (summary || functional breakdown)
-> test scenarios -> detailed test cases -> risk analysis.

Step 1 (collect inputs) happens before the graph is invoked, in
`TestGenerationService`. Step 12 (export) is a separate, on-demand
operation handled by the exports package.
"""
from langgraph.graph import END, StateGraph

from app.agents.test_design_agent.nodes import (
    make_detailed_test_cases_node,
    make_extract_structure_node,
    make_functional_breakdown_node,
    make_normalize_node,
    make_risk_analysis_node,
    make_summary_node,
    make_test_scenarios_node,
)
from app.agents.test_design_agent.state import TestDesignState
from app.llm.base import LLMProvider


def build_test_design_graph(provider: LLMProvider):
    """Compiles the LangGraph workflow bound to the given LLM provider."""
    graph = StateGraph(TestDesignState)

    graph.add_node("normalize", make_normalize_node(provider))
    graph.add_node("extract_structure", make_extract_structure_node(provider))
    graph.add_node("summary", make_summary_node(provider))
    graph.add_node("functional_breakdown", make_functional_breakdown_node(provider))
    graph.add_node("test_scenarios", make_test_scenarios_node(provider))
    graph.add_node("detailed_test_cases", make_detailed_test_cases_node(provider))
    graph.add_node("risk_analysis", make_risk_analysis_node(provider))

    graph.set_entry_point("normalize")
    graph.add_edge("normalize", "extract_structure")
    # Summary and functional breakdown both depend only on
    # normalized_text/structure; run summary first for a fast dashboard
    # preview, then breakdown feeds the rest of the pipeline.
    graph.add_edge("extract_structure", "summary")
    graph.add_edge("summary", "functional_breakdown")
    graph.add_edge("functional_breakdown", "test_scenarios")
    graph.add_edge("test_scenarios", "detailed_test_cases")
    graph.add_edge("detailed_test_cases", "risk_analysis")
    graph.add_edge("risk_analysis", END)

    return graph.compile()
