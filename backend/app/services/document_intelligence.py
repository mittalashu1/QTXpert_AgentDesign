"""AI Document Intelligence orchestration.

The service turns reusable uploaded assets into a QA-facing documentation
baseline: classification, cross-document gap analysis, testability/readiness
scores, evidence-backed findings and an optional published input for Test Design.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.test_design_agent.json_utils import parse_llm_json
from app.config import Settings
from app.database.models.document_intelligence import DocumentAnalysisRun, DocumentFinding
from app.database.models.generation_run import GenerationRun
from app.database.models.requirement import Requirement, RequirementSource, RequirementStatus
from app.database.models.test_case import TestCase
from app.database.models.uploaded_asset import UploadedAsset
from app.database.session import AsyncSessionLocal
from app.llm.base import LLMMessage
from app.llm.factory import get_llm_provider
from app.prompts.document_intelligence_prompts import build_document_review_prompt
from app.services.document_processor import UnsupportedDocumentTypeError, extract_text
from app.services.upload_repository import UploadRepositoryService

logger = logging.getLogger(__name__)

_SCORE_KEYS = (
    "completeness",
    "clarity",
    "consistency",
    "testability",
    "traceability",
    "acceptance_criteria",
    "nfr_coverage",
    "integration_detail",
)

_SEVERITIES = {"critical", "high", "medium", "low"}
_FINDING_STATUSES = {"open", "accepted", "rejected", "resolved", "needs_clarification"}

_DOCUMENT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("API Specification", ("openapi", "swagger", "postman", "api specification", "endpoint")),
    ("Test Strategy", ("test strategy", "quality strategy", "qa strategy")),
    ("Test Plan", ("test plan", "test approach", "entry criteria", "exit criteria")),
    ("Test Cases", ("test case", "expected result", "precondition", "test scenario")),
    ("Security", ("security requirement", "threat", "authentication", "authorization", "encryption")),
    ("Architecture", ("architecture", "high level design", "hld", "low level design", "lld", "component diagram")),
    ("Change Request", ("change request", "change impact", "enhancement request", "cr-")),
    ("Release Notes", ("release note", "known issue", "version released")),
    ("User Stories", ("user story", "as a ", "acceptance criteria", "jira")),
    ("BRD", ("business requirement", "brd", "business objective")),
    ("PRD", ("product requirement", "prd", "product requirement document")),
    ("FSD", ("functional specification", "fsd", "functional design")),
    ("FRD", ("functional requirement", "frd")),
    ("SRS", ("software requirement specification", "srs", "system requirement specification")),
    ("Data Specification", ("data dictionary", "field mapping", "database schema", "data model")),
    ("NFR", ("non-functional", "performance requirement", "availability", "response time", "sla")),
]

_VAGUE_TERMS = (
    "appropriate",
    "quickly",
    "fast",
    "user friendly",
    "as required",
    "as applicable",
    "etc.",
    "and so on",
    "sufficient",
    "reasonable",
    "normally",
    "seamless",
)


def _clamp_score(value: Any, default: int = 50) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _clamp_confidence(value: Any, default: float = 0.8) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _classify_document(filename: str, text: str) -> tuple[str, float]:
    sample = f"{filename}\n{text[:12000]}".lower()
    scores: list[tuple[int, str]] = []
    for document_type, markers in _DOCUMENT_PATTERNS:
        score = sum(sample.count(marker) for marker in markers)
        if score:
            scores.append((score, document_type))
    if scores:
        score, document_type = max(scores)
        return document_type, min(0.98, 0.66 + score * 0.06)
    extension = Path(filename).suffix.lower()
    if extension in {".yaml", ".yml", ".json"} and ("paths:" in sample or '"paths"' in sample):
        return "API Specification", 0.9
    if extension in {".xlsx", ".xls", ".csv"}:
        return "Data Specification", 0.6
    return "Other", 0.45


def _evidence(asset_id: str, filename: str, excerpt: str, reason: str) -> list[dict]:
    return [{
        "asset_id": asset_id,
        "filename": filename,
        "excerpt": excerpt[:500],
        "reason": reason[:500],
    }]


def _finding(
    *,
    asset_id: str | None,
    category: str,
    severity: str,
    title: str,
    description: str,
    testing_impact: str,
    evidence: list[dict] | None = None,
    original_text: str | None = None,
    suggested_refinement: str | None = None,
    confidence: float = 0.9,
) -> dict:
    return {
        "asset_id": asset_id,
        "category": category,
        "severity": severity if severity in _SEVERITIES else "medium",
        "confidence": _clamp_confidence(confidence),
        "title": title[:500],
        "description": description,
        "testing_impact": testing_impact,
        "original_text": original_text,
        "suggested_refinement": suggested_refinement,
        "evidence": evidence or [],
    }


class DocumentIntelligenceService:
    def __init__(self, db: AsyncSession, settings: Settings):
        self.db = db
        self.settings = settings

    async def create_run(
        self,
        *,
        project_id: UUID,
        requested_by_id: UUID,
        asset_ids: list[UUID],
        profile: str,
    ) -> DocumentAnalysisRun:
        unique_ids = list(dict.fromkeys(asset_ids))
        if not unique_ids:
            raise ValueError("Select at least one document to analyze.")
        if len(unique_ids) > 30:
            raise ValueError("Select at most 30 documents in one analysis run.")
        result = await self.db.scalars(
            select(UploadedAsset).where(
                UploadedAsset.id.in_(unique_ids),
                UploadedAsset.owner_id == requested_by_id,
                UploadedAsset.project_id == project_id,
                UploadedAsset.status == "ready",
            )
        )
        assets = list(result.all())
        if len(assets) != len(unique_ids):
            raise ValueError("One or more selected documents are unavailable or do not belong to this project.")
        non_documents = [asset.filename for asset in assets if not UploadRepositoryService.is_reusable_document(asset)]
        if non_documents:
            raise ValueError("Document Intelligence accepts reusable project documents only; choose test data or app builds from their dedicated modules.")
        run = DocumentAnalysisRun(
            project_id=project_id,
            requested_by_id=requested_by_id,
            status="queued",
            profile=profile,
            asset_ids=[str(asset_id) for asset_id in unique_ids],
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run, attribute_names=["findings"])
        return run

    async def analyze_safely(self, run_id: UUID, additional_context: str = "") -> None:
        async with AsyncSessionLocal() as session:
            service = DocumentIntelligenceService(session, self.settings)
            try:
                await service.analyze(run_id, additional_context=additional_context)
            except Exception as exc:  # noqa: BLE001
                logger.exception("document_intelligence_failed run_id=%s", run_id)
                run = await session.get(DocumentAnalysisRun, run_id)
                if run is not None:
                    run.status = "failed"
                    run.error_message = f"{type(exc).__name__}: {exc}"[:4000]
                    await session.commit()

    async def analyze(self, run_id: UUID, additional_context: str = "") -> DocumentAnalysisRun:
        run = await self.db.get(DocumentAnalysisRun, run_id)
        if run is None:
            raise ValueError("Document analysis run not found")
        run.status = "extracting"
        run.error_message = None
        await self.db.commit()

        asset_ids = [UUID(value) for value in run.asset_ids]
        result = await self.db.scalars(
            select(UploadedAsset).where(
                UploadedAsset.id.in_(asset_ids),
                UploadedAsset.owner_id == run.requested_by_id,
                UploadedAsset.project_id == run.project_id,
                UploadedAsset.status == "ready",
            )
        )
        assets_by_id = {asset.id: asset for asset in result.all()}
        if len(assets_by_id) != len(asset_ids):
            raise ValueError("A selected document is no longer available.")

        documents: list[dict] = []
        deterministic_findings: list[dict] = []
        for asset_id in asset_ids:
            asset = assets_by_id[asset_id]
            data = await self._read_asset_bytes(asset)
            try:
                text = extract_text(asset.filename, data)
            except UnsupportedDocumentTypeError:
                text = ""
                deterministic_findings.append(
                    _finding(
                        asset_id=str(asset.id),
                        category="incomplete_requirement",
                        severity="medium",
                        title=f"{asset.filename} cannot yet be text-analyzed",
                        description=(
                            "The file is stored in the project repository but the current Document Intelligence parser cannot extract structured text from this format."
                        ),
                        testing_impact="Content in this file is not included in completeness and consistency checks.",
                        evidence=_evidence(str(asset.id), asset.filename, asset.extension, "Unsupported extraction format"),
                        suggested_refinement="Provide an extractable version or add a supported parser/multimodal analysis path.",
                        confidence=1.0,
                    )
                )
            clean_text = text.strip()
            document_type, classification_confidence = _classify_document(asset.filename, clean_text)
            docs_findings = self._deterministic_document_checks(asset, clean_text, document_type)
            deterministic_findings.extend(docs_findings)
            documents.append({
                "asset_id": str(asset.id),
                "filename": asset.filename,
                "extension": asset.extension,
                "size_bytes": asset.size_bytes,
                "sha256": asset.sha256,
                "detected_document_type": document_type,
                "classification_confidence": classification_confidence,
                # Bound the prompt while retaining enough context for cross-document reasoning.
                "content": clean_text[:22000],
                "content_truncated": len(clean_text) > 22000,
            })

        deterministic_findings.extend(self._deterministic_project_checks(documents, run.profile))
        run.status = "analyzing"
        await self.db.commit()

        existing_context = await self._existing_system_context(run.project_id)
        ai_result: dict[str, Any] | None = None
        try:
            ai_result = await self._ai_review(
                profile=run.profile,
                documents=documents,
                existing_system_context=existing_context,
                deterministic_findings=deterministic_findings,
                additional_context=additional_context[:8000],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Document Intelligence AI enrichment failed; using deterministic fallback: %s", exc)

        result_payload = self._merge_results(documents, deterministic_findings, ai_result)
        await self._persist_result(run, result_payload)
        return await self.get_run(run.id, run.requested_by_id)

    async def _read_asset_bytes(self, asset: UploadedAsset) -> bytes:
        data = bytearray()
        async for chunk in UploadRepositoryService.iter_content(self.db, asset.id):
            data.extend(chunk)
            # Document Analysis is for document/test artifacts, not APK-size binaries.
            if len(data) > self.settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
                raise ValueError(f"{asset.filename} exceeds the Document Intelligence size limit")
        return bytes(data)

    def _deterministic_document_checks(self, asset: UploadedAsset, text: str, document_type: str) -> list[dict]:
        findings: list[dict] = []
        if not text:
            return findings
        lower = text.lower()

        unresolved = list(re.finditer(r"\b(TBD|TBC|TODO|TO BE CONFIRMED|TO BE DEFINED)\b", text, flags=re.I))
        if unresolved:
            excerpt = text[max(0, unresolved[0].start() - 80): unresolved[0].end() + 120]
            findings.append(_finding(
                asset_id=str(asset.id), category="unresolved_tbd", severity="high",
                title=f"{len(unresolved)} unresolved TBD/TBC item(s) in {asset.filename}",
                description="Unresolved placeholders prevent a stable and objectively testable requirement baseline.",
                testing_impact="Expected results or test data may remain undefined.",
                evidence=_evidence(str(asset.id), asset.filename, excerpt, "Unresolved placeholder detected"),
                original_text=excerpt,
                suggested_refinement="Replace each TBD/TBC with the approved value/rule or explicitly record an owner and decision date.",
                confidence=0.99,
            ))

        vague_hits = [term for term in _VAGUE_TERMS if term in lower]
        if vague_hits:
            term = vague_hits[0]
            index = lower.find(term)
            excerpt = text[max(0, index - 100): index + 220]
            findings.append(_finding(
                asset_id=str(asset.id), category="ambiguity", severity="medium",
                title=f"Ambiguous wording in {asset.filename}",
                description=f"Potentially non-measurable wording detected: '{term}'.",
                testing_impact="A tester may not be able to determine a unique pass/fail outcome.",
                evidence=_evidence(str(asset.id), asset.filename, excerpt, "Vague/non-measurable term"),
                original_text=excerpt,
                suggested_refinement="Replace qualitative wording with an observable rule, threshold, state or explicit expected outcome.",
                confidence=0.9,
            ))

        requirement_like = document_type in {"BRD", "PRD", "FRD", "FSD", "SRS", "User Stories", "Change Request"}
        if requirement_like and "acceptance criteria" not in lower and "expected result" not in lower:
            findings.append(_finding(
                asset_id=str(asset.id), category="missing_acceptance_criteria", severity="high",
                title=f"Acceptance criteria are not explicit in {asset.filename}",
                description="The document contains requirement-oriented content but no explicit acceptance-criteria section or equivalent expected outcomes were detected.",
                testing_impact="Test Design must infer expected behavior, increasing ambiguity and false assumptions.",
                evidence=_evidence(str(asset.id), asset.filename, text[:350], "Requirement document lacks explicit acceptance criteria marker"),
                suggested_refinement="Add measurable acceptance criteria for each material business/functional requirement.",
                confidence=0.82,
            ))

        if requirement_like and not any(token in lower for token in ("error", "failure", "invalid", "exception", "reject", "decline")):
            findings.append(_finding(
                asset_id=str(asset.id), category="missing_error_handling", severity="medium",
                title=f"Negative/error behavior is not evident in {asset.filename}",
                description="No material error, failure, invalid-input or recovery behavior was detected in this requirement-oriented document.",
                testing_impact="Negative and recovery tests may lack authoritative expected outcomes.",
                evidence=_evidence(str(asset.id), asset.filename, text[:350], "No negative/error behavior markers detected"),
                suggested_refinement="Define invalid-input, dependency-failure, retry/recovery and user-facing error outcomes where applicable.",
                confidence=0.72,
            ))
        return findings

    def _deterministic_project_checks(self, documents: list[dict], profile: str) -> list[dict]:
        findings: list[dict] = []
        combined = "\n".join(document.get("content", "") for document in documents).lower()
        types = {document.get("detected_document_type") for document in documents}
        if not any(doc_type in types for doc_type in {"BRD", "PRD", "FRD", "FSD", "SRS", "User Stories", "Change Request"}):
            findings.append(_finding(
                asset_id=None, category="missing_requirement", severity="critical",
                title="No primary business/functional requirement baseline detected",
                description="The selected documentation does not contain a recognized BRD/PRD/FRD/FSD/SRS/user-story/change-request source.",
                testing_impact="QTXpert cannot establish authoritative intended behavior for comprehensive test design.",
                suggested_refinement="Add the current approved business/functional requirement source or identify which selected document is authoritative.",
                confidence=0.9,
            ))
        if not any(token in combined for token in ("performance", "response time", "latency", "availability", "throughput", "sla")):
            findings.append(_finding(
                asset_id=None, category="missing_nfr", severity="medium",
                title="Performance/availability NFRs are not evident",
                description="No measurable performance, latency, throughput, availability or SLA requirement was detected across the selected baseline.",
                testing_impact="Performance acceptance criteria cannot be derived objectively.",
                suggested_refinement="Define measurable NFR thresholds and load/environment assumptions where relevant.",
                confidence=0.82,
            ))
        if not any(token in combined for token in ("security", "authentication", "authorization", "role", "permission", "encryption")):
            findings.append(_finding(
                asset_id=None, category="missing_security_control", severity="high",
                title="Security and authorization requirements are not evident",
                description="The selected documentation does not clearly define authentication, authorization, roles/permissions or equivalent security controls.",
                testing_impact="Security and role-based test coverage would rely on assumptions.",
                suggested_refinement="Document applicable identity, role/permission, session and data-protection controls.",
                confidence=0.84,
            ))
        if profile == "banking":
            banking_controls = {
                "transaction limits": ("limit", "maximum amount", "minimum amount"),
                "audit/reconciliation": ("audit", "reconciliation", "ledger"),
                "OTP/MFA": ("otp", "mfa", "one time password", "multi-factor"),
                "reversal/recovery": ("reversal", "reverse", "rollback", "recovery"),
            }
            for name, tokens in banking_controls.items():
                if not any(token in combined for token in tokens):
                    findings.append(_finding(
                        asset_id=None, category="missing_business_rule", severity="high",
                        title=f"Banking control not evident: {name}",
                        description=f"The Banking analysis profile expects explicit {name} behavior where applicable, but it was not detected in the selected baseline.",
                        testing_impact=f"Test coverage for {name} cannot be confidently designed without an authoritative rule or an explicit not-applicable decision.",
                        suggested_refinement=f"Confirm whether {name} applies. If yes, document the exact rules; if not, record it as not applicable.",
                        confidence=0.75,
                    ))
        return findings

    async def _existing_system_context(self, project_id: UUID) -> dict:
        reqs = list((await self.db.scalars(
            select(Requirement).where(Requirement.project_id == project_id).order_by(Requirement.created_at.desc()).limit(25)
        )).all())
        cases_result = await self.db.execute(
            select(TestCase.scenario, TestCase.expected_result)
            .join(GenerationRun, TestCase.generation_run_id == GenerationRun.id)
            .where(GenerationRun.project_id == project_id)
            .order_by(TestCase.created_at.desc())
            .limit(40)
        )
        return {
            "existing_requirements": [
                {"title": req.title, "source": req.source.value, "content": (req.raw_content or "")[:2500]}
                for req in reqs
                if not (req.external_key or "").startswith("document-intelligence:")
            ],
            "existing_test_baseline": [
                {"scenario": row.scenario, "expected_result": row.expected_result}
                for row in cases_result.all()
            ],
        }

    async def _ai_review(
        self,
        *,
        profile: str,
        documents: list[dict],
        existing_system_context: dict,
        deterministic_findings: list[dict],
        additional_context: str,
    ) -> dict:
        provider = get_llm_provider()
        system, user = build_document_review_prompt(
            profile=profile,
            documents=documents,
            existing_system_context=existing_system_context,
            deterministic_findings=deterministic_findings,
            additional_context=additional_context,
        )
        response = await asyncio.wait_for(
            provider.complete(
                [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)],
                response_format_json=True,
                max_tokens=6000,
            ),
            timeout=max(90, self.settings.LLM_REQUEST_TIMEOUT_SECONDS),
        )
        parsed = parse_llm_json(response.content)
        if not isinstance(parsed, dict):
            raise ValueError("AI document review returned a non-object response")
        return parsed

    def _fallback_scores(self, documents: list[dict], findings: list[dict]) -> dict:
        base = {
            "completeness": 78,
            "clarity": 82,
            "consistency": 82,
            "testability": 78,
            "traceability": 68,
            "acceptance_criteria": 72,
            "nfr_coverage": 68,
            "integration_detail": 72,
        }
        if not documents:
            return {key: 0 for key in _SCORE_KEYS}
        penalties = {"critical": 18, "high": 9, "medium": 4, "low": 1}
        total_penalty = sum(penalties.get(str(item.get("severity")), 4) for item in findings)
        per_dimension = min(55, total_penalty // 2)
        for key in base:
            base[key] = max(20, base[key] - per_dimension)
        if any(item.get("category") == "missing_acceptance_criteria" for item in findings):
            base["acceptance_criteria"] = min(base["acceptance_criteria"], 45)
            base["testability"] = min(base["testability"], 60)
        if any(item.get("category") == "missing_nfr" for item in findings):
            base["nfr_coverage"] = min(base["nfr_coverage"], 40)
        if any(item.get("category") in {"cross_document_conflict", "contradiction"} for item in findings):
            base["consistency"] = min(base["consistency"], 50)
        return base

    def _merge_results(self, documents: list[dict], deterministic_findings: list[dict], ai_result: dict | None) -> dict:
        ai_result = ai_result or {}
        valid_asset_ids = {document["asset_id"] for document in documents}
        findings: list[dict] = []
        dedupe: set[tuple[str, str, str]] = set()
        for raw in [*deterministic_findings, *(ai_result.get("findings") or [])]:
            if not isinstance(raw, dict):
                continue
            asset_id = raw.get("asset_id")
            if asset_id and str(asset_id) not in valid_asset_ids:
                asset_id = None
            item = _finding(
                asset_id=str(asset_id) if asset_id else None,
                category=str(raw.get("category") or "incomplete_requirement")[:80],
                severity=str(raw.get("severity") or "medium").lower(),
                confidence=_clamp_confidence(raw.get("confidence"), 0.75),
                title=str(raw.get("title") or "Documentation finding"),
                description=str(raw.get("description") or "Documentation quality issue detected."),
                testing_impact=str(raw.get("testing_impact") or "May reduce the reliability of derived test coverage."),
                evidence=raw.get("evidence") if isinstance(raw.get("evidence"), list) else [],
                original_text=str(raw.get("original_text")) if raw.get("original_text") else None,
                suggested_refinement=str(raw.get("suggested_refinement")) if raw.get("suggested_refinement") else None,
            )
            key = (item["category"], item["title"].lower(), item.get("asset_id") or "")
            if key not in dedupe:
                dedupe.add(key)
                findings.append(item)

        scores = self._fallback_scores(documents, findings)
        if isinstance(ai_result.get("scores"), dict):
            for key in _SCORE_KEYS:
                if key in ai_result["scores"]:
                    scores[key] = _clamp_score(ai_result["scores"][key], scores[key])

        weighted = (
            scores["completeness"] * 0.22
            + scores["testability"] * 0.22
            + scores["consistency"] * 0.16
            + scores["clarity"] * 0.10
            + scores["traceability"] * 0.10
            + scores["acceptance_criteria"] * 0.08
            + scores["nfr_coverage"] * 0.06
            + scores["integration_detail"] * 0.06
        )
        critical_count = sum(1 for item in findings if item["severity"] == "critical")
        high_count = sum(1 for item in findings if item["severity"] == "high")
        readiness_score = _clamp_score(weighted - critical_count * 8 - min(15, high_count * 2), 50)
        if critical_count or readiness_score < 50:
            readiness_status = "not_ready_for_test_design"
        elif readiness_score < 70:
            readiness_status = "needs_refinement"
        elif readiness_score < 85:
            readiness_status = "ready_with_risk"
        else:
            readiness_status = "ready_for_test_design"

        ai_inventory = ai_result.get("document_inventory") if isinstance(ai_result.get("document_inventory"), list) else []
        ai_inventory_by_id = {str(item.get("asset_id")): item for item in ai_inventory if isinstance(item, dict)}
        inventory: list[dict] = []
        for document in documents:
            enriched = ai_inventory_by_id.get(document["asset_id"], {})
            issue_count = sum(1 for item in findings if item.get("asset_id") == document["asset_id"])
            quality_score = _clamp_score(enriched.get("quality_score"), max(25, 90 - issue_count * 8))
            testability_score = _clamp_score(enriched.get("testability_score"), max(20, 88 - issue_count * 9))
            inventory.append({
                "asset_id": document["asset_id"],
                "filename": document["filename"],
                "document_type": str(enriched.get("document_type") or document["detected_document_type"]),
                "classification_confidence": _clamp_confidence(enriched.get("classification_confidence"), document["classification_confidence"]),
                "quality_score": quality_score,
                "testability_score": testability_score,
                "issue_count": issue_count,
                "status": "critical" if any(item["severity"] == "critical" and item.get("asset_id") == document["asset_id"] for item in findings) else "attention" if issue_count else "good",
            })

        knowledge_model = ai_result.get("knowledge_model") if isinstance(ai_result.get("knowledge_model"), dict) else {}
        for key in (
            "business_rules", "functional_requirements", "actors", "user_journeys", "acceptance_criteria",
            "integrations", "dependencies", "validation_rules", "regulatory_requirements",
            "non_functional_requirements", "security_controls", "data_rules", "error_recovery_rules", "open_questions",
        ):
            value = knowledge_model.get(key, [])
            knowledge_model[key] = value if isinstance(value, list) else []

        missing_documents = ai_result.get("missing_documents") if isinstance(ai_result.get("missing_documents"), list) else []
        recommendations = ai_result.get("recommendations") if isinstance(ai_result.get("recommendations"), list) else []
        summary = str(ai_result.get("summary") or "QTXpert completed a documentation quality and testability review using deterministic QA checks. AI enrichment was unavailable for this run.")
        return {
            "document_inventory": inventory,
            "scores": scores,
            "knowledge_model": knowledge_model,
            "findings": findings,
            "missing_documents": missing_documents,
            "recommendations": [str(item) for item in recommendations][:50],
            "summary": summary,
            "readiness_score": readiness_score,
            "readiness_status": readiness_status,
        }

    async def _persist_result(self, run: DocumentAnalysisRun, payload: dict) -> None:
        await self.db.execute(delete(DocumentFinding).where(DocumentFinding.run_id == run.id))
        for index, finding in enumerate(payload["findings"], start=1):
            asset_id = UUID(finding["asset_id"]) if finding.get("asset_id") else None
            self.db.add(DocumentFinding(
                run_id=run.id,
                asset_id=asset_id,
                finding_key=f"DA-{index:04d}",
                category=finding["category"],
                severity=finding["severity"],
                confidence=finding["confidence"],
                title=finding["title"],
                description=finding["description"],
                testing_impact=finding.get("testing_impact"),
                original_text=finding.get("original_text"),
                suggested_refinement=finding.get("suggested_refinement"),
                evidence=finding.get("evidence") or [],
                status="open",
            ))
        run.document_inventory = payload["document_inventory"]
        run.knowledge_model = payload["knowledge_model"]
        run.scores = payload["scores"]
        run.missing_documents = payload["missing_documents"]
        run.recommendations = payload["recommendations"]
        run.readiness_score = payload["readiness_score"]
        run.readiness_status = payload["readiness_status"]
        run.summary = payload["summary"]
        run.status = "completed"
        run.error_message = None
        await self.db.commit()

    async def get_run(self, run_id: UUID, owner_id: UUID) -> DocumentAnalysisRun:
        run = await self.db.scalar(
            select(DocumentAnalysisRun)
            .options(selectinload(DocumentAnalysisRun.findings))
            .where(DocumentAnalysisRun.id == run_id, DocumentAnalysisRun.requested_by_id == owner_id)
        )
        if run is None:
            raise FileNotFoundError(str(run_id))
        return run

    async def latest_run(self, project_id: UUID, owner_id: UUID) -> DocumentAnalysisRun | None:
        run = await self.db.scalar(
            select(DocumentAnalysisRun)
            .options(selectinload(DocumentAnalysisRun.findings))
            .where(DocumentAnalysisRun.project_id == project_id, DocumentAnalysisRun.requested_by_id == owner_id)
            .order_by(DocumentAnalysisRun.created_at.desc())
            .limit(1)
        )
        return run

    async def review_finding(
        self,
        finding_id: UUID,
        owner_id: UUID,
        *,
        status: str,
        resolution_note: str | None,
        suggested_refinement: str | None,
    ) -> DocumentFinding:
        if status not in _FINDING_STATUSES:
            raise ValueError("Invalid finding review status")
        finding = await self.db.scalar(
            select(DocumentFinding)
            .join(DocumentAnalysisRun, DocumentFinding.run_id == DocumentAnalysisRun.id)
            .where(DocumentFinding.id == finding_id, DocumentAnalysisRun.requested_by_id == owner_id)
        )
        if finding is None:
            raise FileNotFoundError(str(finding_id))
        finding.status = status
        finding.resolution_note = resolution_note
        if suggested_refinement is not None:
            finding.suggested_refinement = suggested_refinement
        await self.db.commit()
        await self.db.refresh(finding)
        return finding

    async def publish_to_test_design(self, run_id: UUID, owner_id: UUID) -> Requirement:
        run = await self.get_run(run_id, owner_id)
        if run.status != "completed":
            raise ValueError("Wait for Document Intelligence analysis to complete before publishing.")
        knowledge = run.knowledge_model or {}
        open_findings = [
            {"key": item.finding_key, "severity": item.severity, "title": item.title, "testing_impact": item.testing_impact}
            for item in run.findings
            if item.status not in {"rejected", "resolved"}
        ]
        baseline = {
            "document_readiness": {
                "score": run.readiness_score,
                "status": run.readiness_status,
                "scores": run.scores or {},
            },
            "summary": run.summary,
            "knowledge_model": knowledge,
            "open_documentation_findings": open_findings,
            "analysis_run_id": str(run.id),
        }
        raw_content = json.dumps(baseline, ensure_ascii=False, indent=2)
        external_key = f"document-intelligence:{run.project_id}"
        requirement = await self.db.scalar(
            select(Requirement).where(
                Requirement.project_id == run.project_id,
                Requirement.external_key == external_key,
            )
        )
        if requirement is None:
            requirement = Requirement(
                project_id=run.project_id,
                external_key=external_key,
                title="QTXpert AI Document Intelligence Baseline",
                source=RequirementSource.BRD_UPLOAD,
                status=RequirementStatus.NORMALIZED,
                raw_content=raw_content,
                normalized_content=raw_content,
                extracted_metadata={"document_intelligence": baseline},
                source_file_path=f"document-intelligence:{run.id}",
            )
            self.db.add(requirement)
        else:
            requirement.title = "QTXpert AI Document Intelligence Baseline"
            requirement.status = RequirementStatus.NORMALIZED
            requirement.raw_content = raw_content
            requirement.normalized_content = raw_content
            requirement.extracted_metadata = {"document_intelligence": baseline}
            requirement.source_file_path = f"document-intelligence:{run.id}"
        await self.db.flush()
        run.published_requirement_id = requirement.id
        await self.db.commit()
        await self.db.refresh(requirement)
        return requirement
