import io
import json
import uuid
from types import SimpleNamespace

import openpyxl

from app.config import Settings
from app.services.document_intelligence import DocumentIntelligenceService, _classify_document
from app.services.document_processor import extract_text


class DummyAsset:
    def __init__(self, filename: str, text: str = ""):
        self.id = uuid.uuid4()
        self.filename = filename
        self.extension = filename.rsplit(".", 1)[-1]
        self.size_bytes = len(text.encode())
        self.sha256 = "a" * 64


def test_classifies_business_and_api_documents():
    assert _classify_document("Retail_BRD_v3.docx", "Business Requirements and business objectives")[0] == "BRD"
    assert _classify_document("payments-openapi.yaml", "openapi: 3.0\npaths:\n  /payments:")[0] == "API Specification"


def test_deterministic_checks_find_ambiguity_tbd_and_acceptance_gap():
    service = DocumentIntelligenceService(None, Settings())  # type: ignore[arg-type]
    asset = DummyAsset("Mobile_FSD.docx")
    findings = service._deterministic_document_checks(
        asset,  # type: ignore[arg-type]
        "Functional specification. The system should respond quickly. Transfer limit is TBD.",
        "FSD",
    )
    categories = {finding["category"] for finding in findings}
    assert "ambiguity" in categories
    assert "unresolved_tbd" in categories
    assert "missing_acceptance_criteria" in categories


def test_banking_profile_detects_missing_controls():
    service = DocumentIntelligenceService(None, Settings())  # type: ignore[arg-type]
    findings = service._deterministic_project_checks(
        [{"content": "Business requirement. User logs into the application.", "detected_document_type": "BRD"}],
        "banking",
    )
    titles = " ".join(finding["title"] for finding in findings)
    assert "OTP/MFA" in titles
    assert "audit/reconciliation" in titles
    assert "reversal/recovery" in titles


def test_readiness_is_not_ready_when_critical_gap_exists():
    service = DocumentIntelligenceService(None, Settings())  # type: ignore[arg-type]
    documents = [{
        "asset_id": str(uuid.uuid4()),
        "filename": "architecture.pdf",
        "detected_document_type": "Architecture",
        "classification_confidence": 0.9,
    }]
    deterministic = [{
        "asset_id": None,
        "category": "missing_requirement",
        "severity": "critical",
        "confidence": 0.9,
        "title": "No primary baseline",
        "description": "Missing requirement baseline",
        "testing_impact": "Cannot derive tests",
        "evidence": [],
        "original_text": None,
        "suggested_refinement": "Add a BRD",
    }]
    result = service._merge_results(documents, deterministic, None)
    assert result["readiness_status"] == "not_ready_for_test_design"
    assert result["readiness_score"] < 70


def test_json_extractor_preserves_openapi_contract():
    payload = {"openapi": "3.0.0", "paths": {"/payments": {"post": {"responses": {"200": {}}}}}}
    text = extract_text("api.json", json.dumps(payload).encode())
    assert "openapi" in text
    assert "/payments" in text


def test_xlsx_extractor_preserves_sheet_and_cells():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Test Cases"
    sheet.append(["ID", "Scenario", "Expected"])
    sheet.append(["TC-1", "Valid login", "Dashboard displayed"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    text = extract_text("existing-tests.xlsx", buffer.getvalue())
    assert "[SHEET: Test Cases]" in text
    assert "Valid login" in text
    assert "Dashboard displayed" in text


def test_context_payload_is_bounded_redacted_and_evidence_led():
    service = DocumentIntelligenceService(None, Settings())  # type: ignore[arg-type]
    asset_id = uuid.uuid4()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="completed",
        profile="banking",
        additional_context="Validate the transfer journey in staging; password: secret-value",
        readiness_score=62,
        readiness_status="needs_refinement",
        summary="Review password: secret-value and confirm the transfer rule.",
        document_inventory=[{"filename": "Payments BRD.docx", "document_type": "BRD"}],
        knowledge_model={"business_rules": ["Transfer limit is pending confirmation."], "open_questions": ["Who approves a reversal?"]},
        findings=[SimpleNamespace(
            status="open",
            severity="high",
            title="Missing reversal rule",
            testing_impact="The expected recovery outcome is not defined.",
            description="A reversal rule is absent.",
        )],
        asset_ids=[str(asset_id)],
        published_requirement_id=None,
    )

    payload = service.build_context_payload(run)

    assert payload["asset_ids"] == [asset_id]
    assert "static evidence; not runtime proof" in payload["context"]
    assert "password: [REDACTED]" in payload["context"]
    assert "secret-value" not in payload["context"]
    assert "Change/scope context:" in payload["context"]
    assert "Missing reversal rule" in payload["context"]


def test_document_text_redacts_credentials_before_evidence_or_ai():
    service = DocumentIntelligenceService(None, Settings())  # type: ignore[arg-type]
    safe = service._redact_sensitive_text(
        "Password: super-secret\nAuthorization: Bearer abcdefghijklmnop.example-token\n{\"client_secret\": \"json-secret\"}"
    )
    assert "super-secret" not in safe
    assert "abcdefghijklmnop" not in safe
    assert "json-secret" not in safe
    assert "Password: [REDACTED]" in safe
    assert "Bearer [REDACTED]" in safe
