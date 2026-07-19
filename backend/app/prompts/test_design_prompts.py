"""
Prompt templates for the AI Test Design Agent workflow.

Each function returns a (system, user) message pair for one workflow step.
Keeping prompts in one module (rather than inline in the graph nodes) lets
the Prompt Library feature in the frontend list and version them later.
"""
from typing import List

TEST_CASE_TYPES = [
    "Functional", "Negative", "Boundary", "Integration", "API", "Database",
    "Security", "Accessibility", "Usability", "Performance", "Regression",
    "Exploratory", "Data Validation", "Workflow", "Role Based", "Permission",
    "Maker Checker", "Error Handling", "Localization", "Browser Compatibility",
    "Mobile", "Cross Platform",
]

BASE_SYSTEM = (
    "You are QTXpert.ai's AI Test Design Agent, an expert QA architect that "
    "produces enterprise-grade software test artifacts for banking, retail, "
    "SaaS, and government organizations. Always respond with valid JSON only "
    "- no markdown fences, no commentary - matching exactly the schema "
    "described in the user message."
)


def normalize_requirements_prompt(raw_documents: List[str]) -> tuple[str, str]:
    joined = "\n\n---DOCUMENT BOUNDARY---\n\n".join(raw_documents)
    user = f"""Normalize the following raw requirement documents into a single
clean, de-duplicated requirements corpus. Remove document boilerplate,
resolve inconsistent terminology, and merge overlapping statements while
preserving every distinct requirement.

Respond as JSON: {{"normalized_text": string}}

RAW DOCUMENTS:
{joined}
"""
    return BASE_SYSTEM, user


def extract_structure_prompt(normalized_text: str) -> tuple[str, str]:
    user = f"""Analyze the normalized requirements below and extract structured
elements. Respond as JSON with this exact schema:
{{
  "business_rules": [string],
  "functional_requirements": [string],
  "actors": [string],
  "user_journeys": [string],
  "acceptance_criteria": [string],
  "integrations": [string],
  "dependencies": [string],
  "validation_rules": [string],
  "regulatory_requirements": [string],
  "non_functional_requirements": [string]
}}

REQUIREMENTS:
{normalized_text}
"""
    return BASE_SYSTEM, user


def requirement_summary_prompt(normalized_text: str) -> tuple[str, str]:
    user = f"""Write a concise executive requirement summary (250-400 words)
for the requirements below, suitable for a QA lead dashboard.

Respond as JSON: {{"summary": string}}

REQUIREMENTS:
{normalized_text}
"""
    return BASE_SYSTEM, user


def functional_breakdown_prompt(normalized_text: str, structure: dict) -> tuple[str, str]:
    user = f"""Break the requirements into discrete testable functional units.
Each unit should be independently verifiable.

Respond as JSON: {{"functional_breakdown": [
  {{"unit_id": string, "title": string, "description": string,
    "related_actors": [string], "related_rules": [string]}}
]}}

REQUIREMENTS:
{normalized_text}

EXTRACTED STRUCTURE:
{structure}
"""
    return BASE_SYSTEM, user


def test_scenarios_prompt(functional_breakdown: list) -> tuple[str, str]:
    user = f"""For each functional unit below, generate high-level test
scenarios covering positive, negative, and edge conditions.

Respond as JSON: {{"test_scenarios": [
  {{"scenario_id": string, "unit_id": string, "title": string,
    "test_types": [one or more of {TEST_CASE_TYPES}]}}
]}}

FUNCTIONAL UNITS:
{functional_breakdown}
"""
    return BASE_SYSTEM, user


def detailed_test_cases_prompt(scenario: dict, structure: dict) -> tuple[str, str]:
    user = f"""Generate detailed enterprise test cases for the scenario below.
Produce 2-6 test cases depending on scenario complexity. Every field is
mandatory.

Respond as JSON: {{"test_cases": [
  {{
    "requirement_traceability": string,
    "test_type": one of {TEST_CASE_TYPES},
    "scenario": string,
    "objective": string,
    "priority": "critical|high|medium|low",
    "severity": "blocker|critical|major|minor|trivial",
    "preconditions": string,
    "test_data": object,
    "steps": [string],
    "expected_result": string,
    "post_conditions": string,
    "is_automation_candidate": boolean,
    "automation_type": string or null,
    "risk_level": "high|medium|low"
  }}
]}}

SCENARIO:
{scenario}

RELEVANT STRUCTURE (business rules, validation rules, regulatory requirements):
{structure}
"""
    return BASE_SYSTEM, user


def risk_analysis_prompt(structure: dict, test_cases_summary: dict) -> tuple[str, str]:
    user = f"""Perform a QA risk analysis over the requirements and generated
test coverage below. Identify coverage gaps, high-risk areas, and
recommended mitigations.

Respond as JSON: {{
  "overall_risk_level": "high|medium|low",
  "high_risk_areas": [{{"area": string, "reason": string, "mitigation": string}}],
  "coverage_gaps": [string],
  "recommendations": [string]
}}

STRUCTURE:
{structure}

TEST COVERAGE SUMMARY:
{test_cases_summary}
"""
    return BASE_SYSTEM, user
