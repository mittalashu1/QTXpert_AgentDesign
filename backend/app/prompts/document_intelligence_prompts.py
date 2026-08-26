"""Prompt contract for QTXpert AI Document Intelligence."""
from __future__ import annotations

import json


PROFILE_GUIDANCE = {
    "general": "Apply enterprise software quality-engineering best practices across functional, integration, data, security, NFR and operational requirements.",
    "banking": (
        "Apply banking/financial-services QA controls: authorization and maker-checker, transaction limits, fees, currency/rounding, OTP/MFA, session security, "
        "transaction states, reversals, reconciliation, idempotency, settlement, audit trail, PII/privacy, regulatory controls, error/recovery and customer notifications."
    ),
    "retail": "Apply retail/e-commerce controls: catalogue, pricing, promotions, inventory, cart, checkout, payment, fulfilment, returns, tax, identity, fraud and customer communication.",
    "saas": "Apply SaaS controls: tenant isolation, roles/permissions, subscription/entitlement, APIs/webhooks, configuration, data retention, availability, observability and upgrade compatibility.",
    "government": "Apply public-sector controls: identity, accessibility, privacy, auditability, records retention, authorization, service availability, regulatory/policy compliance and citizen-facing error handling.",
}


def _compact_documents(documents: list[dict], max_total_chars: int = 90_000) -> list[dict]:
    """Bound multi-document context while retaining evidence from every file.

    The Upload Repository can hold dozens of large documents. Sending every
    extracted character to one model request is costly and can exceed provider
    context limits. Allocate a fair bounded excerpt to each selected document;
    deterministic checks still inspect the complete extracted text before this
    prompt is built.
    """
    if not documents:
        return []
    remaining = max_total_chars
    compact: list[dict] = []
    for index, document in enumerate(documents):
        docs_left = max(1, len(documents) - index)
        allowance = min(12_000, max(2_000, remaining // docs_left))
        content = str(document.get("content") or "")
        item = {key: value for key, value in document.items() if key != "content"}
        item["content"] = content[:allowance]
        item["content_truncated_for_ai"] = bool(
            document.get("content_truncated") or len(content) > allowance
        )
        compact.append(item)
        remaining = max(0, remaining - len(item["content"]))
    return compact


def _compact_existing_context(existing_system_context: dict) -> dict:
    requirements = list(existing_system_context.get("existing_requirements") or [])[:12]
    tests = list(existing_system_context.get("existing_test_baseline") or [])[:25]
    compact_requirements = []
    for item in requirements:
        if not isinstance(item, dict):
            continue
        compact_requirements.append({
            **{key: value for key, value in item.items() if key != "content"},
            "content": str(item.get("content") or "")[:1800],
        })
    compact_tests = []
    for item in tests:
        if not isinstance(item, dict):
            continue
        compact_tests.append({
            "scenario": str(item.get("scenario") or "")[:500],
            "expected_result": str(item.get("expected_result") or "")[:700],
        })
    return {
        "existing_requirements": compact_requirements,
        "existing_test_baseline": compact_tests,
    }


def build_document_review_prompt(
    *,
    profile: str,
    documents: list[dict],
    existing_system_context: dict,
    deterministic_findings: list[dict],
    additional_context: str,
) -> tuple[str, str]:
    guidance = PROFILE_GUIDANCE.get(profile, PROFILE_GUIDANCE["general"])
    prompt_documents = _compact_documents(documents)
    prompt_baseline = _compact_existing_context(existing_system_context)
    prompt_findings = deterministic_findings[:80]
    system = (
        "You are QTXpert's AI Document Intelligence engine and a senior QA architect. "
        "Your purpose is to determine whether project documentation is complete, clear, internally consistent, testable and sufficient to create objective software tests. "
        "Use only supplied evidence. Never invent business rules, limits, SLAs, roles, API behavior or regulatory requirements. "
        "When information is missing, report the gap and propose wording with placeholders such as <confirm value> rather than fabricating a value. "
        "Cross-check documents against each other and against the supplied existing-system baseline. "
        "Some long files may be marked content_truncated_for_ai; do not treat omitted tail content as proof that a requirement is missing. Deterministic pre-checks were run on the full extracted text. "
        "Return one valid JSON object only, without markdown."
    )
    user = f"""DOCUMENT REVIEW PROFILE: {profile}\nPROFILE GUIDANCE: {guidance}\n\nADDITIONAL USER CONTEXT:\n{additional_context or 'None provided'}\n\nDOCUMENTS:\n{json.dumps(prompt_documents, ensure_ascii=False)}\n\nEXISTING SYSTEM BASELINE:\n{json.dumps(prompt_baseline, ensure_ascii=False)}\n\nDETERMINISTIC PRE-CHECK FINDINGS:\n{json.dumps(prompt_findings, ensure_ascii=False)}\n\nAnalyze the complete project documentation as a coherent baseline, not as isolated files. Return exactly this JSON shape:\n{{\n  \"summary\": \"concise QA-facing documentation assessment\",\n  \"document_inventory\": [\n    {{\"asset_id\": \"uuid\", \"filename\": \"name\", \"document_type\": \"BRD|PRD|FRD|FSD|SRS|User Stories|Architecture|API Specification|Data Specification|Security|NFR|Test Strategy|Test Plan|Test Cases|Change Request|Release Notes|Other\", \"classification_confidence\": 0.0, \"quality_score\": 0, \"testability_score\": 0, \"issue_count\": 0, \"status\": \"good|attention|critical\"}}\n  ],\n  \"scores\": {{\"completeness\": 0, \"clarity\": 0, \"consistency\": 0, \"testability\": 0, \"traceability\": 0, \"acceptance_criteria\": 0, \"nfr_coverage\": 0, \"integration_detail\": 0}},\n  \"knowledge_model\": {{\n    \"business_rules\": [string], \"functional_requirements\": [string], \"actors\": [string], \"user_journeys\": [string],\n    \"acceptance_criteria\": [string], \"integrations\": [string], \"dependencies\": [string], \"validation_rules\": [string],\n    \"regulatory_requirements\": [string], \"non_functional_requirements\": [string], \"security_controls\": [string],\n    \"data_rules\": [string], \"error_recovery_rules\": [string], \"open_questions\": [string]\n  }},\n  \"findings\": [\n    {{\"asset_id\": \"uuid or null\", \"category\": \"missing_requirement|incomplete_requirement|ambiguity|non_testable|contradiction|duplicate|missing_acceptance_criteria|missing_business_rule|missing_validation|missing_error_handling|missing_boundary|missing_role_permission|missing_integration|missing_data_mapping|missing_api_contract|missing_security_control|missing_nfr|missing_regulatory|missing_audit_logging|missing_recovery|missing_dependency|broken_traceability|cross_document_conflict|obsolete_requirement|unresolved_tbd|change_impact_gap|existing_system_conflict\", \"severity\": \"critical|high|medium|low\", \"confidence\": 0.0, \"title\": string, \"description\": string, \"testing_impact\": string, \"original_text\": string or null, \"suggested_refinement\": string or null, \"evidence\": [{{\"asset_id\": \"uuid or null\", \"filename\": string, \"excerpt\": string, \"reason\": string}}]}}\n  ],\n  \"missing_documents\": [{{\"document_type\": string, \"priority\": \"high|medium|low\", \"reason\": string}}],\n  \"recommendations\": [string]\n}}\n\nScoring rules: 0 means unusable/missing, 100 means strong and objectively testable. Evidence excerpts must be short and copied/paraphrased from supplied text. A finding without evidence is allowed only when the finding is itself about a missing document or missing category.\n"""
    return system, user
