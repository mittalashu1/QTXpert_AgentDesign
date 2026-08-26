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
        item["content_truncated_for_ai"] = bool(document.get("content_truncated") or len(content) > allowance)
        compact.append(item)
        remaining = max(0, remaining - len(item["content"]))
    return compact


def _compact_existing_context(existing_system_context: dict) -> dict:
    requirements = list(existing_system_context.get("existing_requirements") or [])[:12]
    tests = list(existing_system_context.get("existing_test_baseline") or [])[:25]
    return {
        "existing_requirements": [
            {
                **{key: value for key, value in item.items() if key != "content"},
                "content": str(item.get("content") or "")[:1800],
            }
            for item in requirements
            if isinstance(item, dict)
        ],
        "existing_test_baseline": [
            {
                "scenario": str(item.get("scenario") or "")[:500],
                "expected_result": str(item.get("expected_result") or "")[:700],
            }
            for item in tests
            if isinstance(item, dict)
        ],
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
    change_context = additional_context.strip()

    system = (
        "You are QTXpert's AI Document Intelligence engine and a senior QA architect. "
        "Assess whether the complete project documentation is sufficient, consistent and objectively testable for the stated change or scope. "
        "Treat the uploaded project documents, the existing-system baseline, and the user's change context as one evidence set. "
        "If change context is supplied, every score and document assessment must reflect fitness for that change, not generic document quality alone. "
        "Use only supplied evidence. Never invent business rules, limits, SLAs, roles, API behavior or regulatory requirements. "
        "When information is missing, report a gap and use placeholders such as <confirm value> rather than fabricating values. "
        "Cross-check new/change material against existing requirements and tests to identify omissions, contradictions and change-impact gaps. "
        "Some files may be truncated for the AI prompt; do not treat omitted tail content as proof that something is missing. "
        "Return one valid JSON object only, without markdown."
    )

    user = f"""DOCUMENT REVIEW PROFILE: {profile}\nPROFILE GUIDANCE: {guidance}\n\nCHANGE / SCOPE CONTEXT:\n{change_context or 'No explicit change context supplied. Assess overall documentation readiness.'}\n\nCURRENT PROJECT DOCUMENTATION:\n{json.dumps(prompt_documents, ensure_ascii=False)}\n\nEXISTING SYSTEM BASELINE:\n{json.dumps(prompt_baseline, ensure_ascii=False)}\n\nDETERMINISTIC QA PRE-CHECKS:\n{json.dumps(prompt_findings, ensure_ascii=False)}\n\nAnalyze the project as one documentation baseline. Return exactly this JSON shape:\n{{\n  \"summary\": \"one concise executive QA assessment\",\n  \"document_inventory\": [\n    {{\"asset_id\": \"uuid\", \"filename\": \"name\", \"document_type\": \"BRD|PRD|FRD|FSD|SRS|User Stories|Architecture|API Specification|Data Specification|Security|NFR|Test Strategy|Test Plan|Test Cases|Change Request|Release Notes|Other\", \"classification_confidence\": 0.0, \"quality_score\": 0, \"testability_score\": 0, \"issue_count\": 0, \"status\": \"good|attention|critical\"}}\n  ],\n  \"scores\": {{\"completeness\": 0, \"clarity\": 0, \"consistency\": 0, \"testability\": 0, \"traceability\": 0, \"acceptance_criteria\": 0, \"nfr_coverage\": 0, \"integration_detail\": 0}},\n  \"knowledge_model\": {{\n    \"business_rules\": [string], \"functional_requirements\": [string], \"actors\": [string], \"user_journeys\": [string],\n    \"acceptance_criteria\": [string], \"integrations\": [string], \"dependencies\": [string], \"validation_rules\": [string],\n    \"regulatory_requirements\": [string], \"non_functional_requirements\": [string], \"security_controls\": [string],\n    \"data_rules\": [string], \"error_recovery_rules\": [string], \"open_questions\": [string]\n  }},\n  \"findings\": [\n    {{\"asset_id\": \"uuid or null\", \"category\": \"missing_requirement|incomplete_requirement|ambiguity|non_testable|contradiction|duplicate|missing_acceptance_criteria|missing_business_rule|missing_validation|missing_error_handling|missing_boundary|missing_role_permission|missing_integration|missing_data_mapping|missing_api_contract|missing_security_control|missing_nfr|missing_regulatory|missing_audit_logging|missing_recovery|missing_dependency|broken_traceability|cross_document_conflict|obsolete_requirement|unresolved_tbd|change_impact_gap|existing_system_conflict\", \"severity\": \"critical|high|medium|low\", \"confidence\": 0.0, \"title\": string, \"description\": string, \"testing_impact\": string, \"original_text\": string or null, \"suggested_refinement\": string or null, \"evidence\": [{{\"asset_id\": \"uuid or null\", \"filename\": string, \"excerpt\": string, \"reason\": string}}]}}\n  ],\n  \"missing_documents\": [{{\"document_type\": string, \"priority\": \"high|medium|low\", \"reason\": string}}],\n  \"recommendations\": [string]\n}}\n\nScoring rules: 0 means the current documentation does not support the stated change/area; 100 means it is complete, consistent and objectively testable for the stated change. For each document, quality_score and testability_score must reflect how well that document contributes to the current change/scope. Evidence must be concise and grounded in supplied material.\n"""
    return system, user
