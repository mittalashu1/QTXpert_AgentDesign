"""Durable workflow and provenance helpers for QTXpert Autopilot.

The original Autopilot implementation had a useful analysis/discovery/suite
pipeline, but the lifecycle was implicit in a handful of strings.  This module
keeps the state machine small and deterministic so API workers, the UI and
future queue consumers can all validate the same transitions.  It also
contains pure helpers for building a reviewable plan, projecting the observed
application map and detecting duplicate coverage without ever handling secret
values.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from app.schemas.autopilot import (
    AutopilotAnalysis,
    AutopilotApplicationMap,
    AutopilotGenerationPlan,
    AutopilotPlanItem,
    AutopilotTest,
    DiscoveredScreen,
    DiscoveredTransition,
)


WORKFLOW_PHASES = (
    "draft",
    "preflight",
    "context_ready",
    "plan_pending_review",
    "plan_approved",
    "exploring",
    "cases_pending_review",
    "cases_approved",
    "execution_ready",
    "running",
    "completed",
    "partial",
    "blocked",
    "failed",
)

TERMINAL_PHASES = frozenset({"completed", "partial", "blocked", "failed"})

# Same-phase updates are idempotent.  A worker may retry a transition after a
# timeout, so the table deliberately allows the normal resumable paths while
# rejecting accidental jumps that would skip a user approval or runtime gate.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    # Jobs created before the explicit workflow contract may still be stored
    # as ``draft`` when Runtime Discovery is the first durable operation.  A
    # discovered map must be allowed to move those legacy jobs to the review
    # gate (or to blocked when the provider cannot attach) instead of silently
    # skipping the manifest update.
    "draft": frozenset({"preflight", "context_ready", "cases_pending_review", "blocked", "failed"}),
    "preflight": frozenset({"context_ready", "plan_pending_review", "failed"}),
    "context_ready": frozenset({"plan_pending_review", "plan_approved", "failed"}),
    "plan_pending_review": frozenset({"plan_approved", "context_ready", "exploring", "failed"}),
    "plan_approved": frozenset({"exploring", "execution_ready", "failed"}),
    "exploring": frozenset({"cases_pending_review", "cases_approved", "execution_ready", "partial", "blocked", "failed"}),
    "cases_pending_review": frozenset({"cases_approved", "exploring", "execution_ready", "failed"}),
    "cases_approved": frozenset({"execution_ready", "exploring", "failed"}),
    "execution_ready": frozenset({"running", "exploring", "failed"}),
    # A checkpoint continuation may arrive while the auto-run safe suite is
    # already executing (the UI can submit the optional setup dialog after
    # discovery has handed off to the suite).  Treat the re-entry into the
    # exploration phase as idempotent instead of surfacing a false worker
    # failure; the active suite remains the single source of execution truth.
    "running": frozenset({"completed", "partial", "blocked", "failed", "execution_ready", "exploring", "cases_pending_review"}),
    "completed": frozenset({"plan_pending_review", "exploring", "execution_ready"}),
    # A partially completed legacy run can be reopened from the report's
    # explicit "Approve & discover" action.  Treat that as a valid resumable
    # gate instead of surfacing an invalid partial -> plan_approved error.
    "partial": frozenset({"exploring", "execution_ready", "running", "plan_pending_review", "plan_approved", "cases_approved"}),
    "blocked": frozenset({"exploring", "execution_ready", "plan_pending_review"}),
    "failed": frozenset({"preflight", "context_ready", "plan_pending_review", "exploring"}),
}


def transition_phase(current: str | None, target: str) -> str:
    """Validate and return a workflow phase transition.

    ``ValueError`` is intentionally used so both HTTP routes and background
    workers can map the same failure to a clear 409/retry message.
    """

    source = (current or "draft").strip().lower()
    destination = (target or "").strip().lower()
    if source not in WORKFLOW_PHASES:
        raise ValueError(f"Unknown Autopilot phase: {source or '<empty>'}")
    if destination not in WORKFLOW_PHASES:
        raise ValueError(f"Unknown Autopilot phase: {destination or '<empty>'}")
    if source != destination and destination not in ALLOWED_TRANSITIONS[source]:
        raise ValueError(f"Invalid Autopilot phase transition: {source} -> {destination}")
    return destination


def phase_for_job(job: Mapping[str, Any]) -> str:
    """Infer a phase for manifests created before the explicit field existed."""

    raw = str(job.get("phase") or "").strip().lower()
    if raw in WORKFLOW_PHASES:
        return raw
    status = str(job.get("status") or "").lower()
    stage = str(job.get("stage") or "").lower()
    if status == "failed" or stage == "failed":
        return "failed"
    if status == "waiting_for_input":
        return "cases_pending_review" if stage == "case_review" else "context_ready"
    if stage in {"ready_for_discovery", "runtime_discovery"}:
        return "plan_approved"
    if stage in {"input_collection", "validating_inputs"}:
        return "context_ready"
    if stage in {"ready_for_execution", "execution_ready"}:
        return "execution_ready"
    if stage in {"complete", "completed"} or status == "analyzed":
        return "completed"
    if status == "analyzing":
        return "preflight"
    return "draft"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_refs(test: AutopilotTest) -> list[str]:
    refs = [*test.source_refs]
    refs.extend(item.reference for item in test.provenance if item.reference)
    return list(dict.fromkeys(str(item) for item in refs if str(item).strip()))


def build_generation_plan(
    analysis: AutopilotAnalysis,
    *,
    plan_id: str | None = None,
    version: int = 1,
    status: str = "pending_review",
) -> AutopilotGenerationPlan:
    """Compile tests into concise user-facing coverage sections.

    The plan is intentionally grouped by observable test type rather than by
    opaque URL or generated test ID.  Every item keeps source references and a
    count so the user can edit/approve scope without losing provenance.
    """

    grouped: dict[str, list[AutopilotTest]] = {}
    for test in analysis.tests:
        bucket = str(test.bucket or "functional")
        grouped.setdefault(bucket, []).append(test)
    labels = {
        "installation": "Install and launch",
        "page_level": "Pages and navigation",
        "functional": "Functional journeys",
        "functional_positive": "Functional · positive",
        "functional_negative": "Functional · negative",
        "uat": "User acceptance journeys",
        "ui": "UI quality",
        "ui_positive": "UI · positive",
        "ui_negative": "UI · negative",
        "accessibility": "Accessibility",
        "integration": "Service integration",
        "sit": "System integration",
        "performance": "Performance signals",
        "security": "Security guardrails",
        "compatibility": "Device and browser compatibility",
        "resilience": "Recovery and resilience",
        "permissions": "Permissions",
        "regression": "Regression coverage",
    }
    items: list[AutopilotPlanItem] = []
    for index, (bucket, tests) in enumerate(grouped.items(), start=1):
        refs = list(dict.fromkeys(ref for test in tests for ref in _source_refs(test)))
        high_risk = any(test.priority in {"critical", "high"} for test in tests)
        approval = any(test.destructive or test.requires_auth for test in tests)
        items.append(
            AutopilotPlanItem(
                id=f"scope-{index:03d}-{bucket}",
                title=labels.get(bucket, bucket.replace("_", " ").title()),
                description=(
                    f"{len(tests)} grounded case(s) from the supplied target evidence. "
                    "Cases remain pending when a live control, credential, data fixture or approval is missing."
                ),
                test_type=bucket,
                status="planned",
                source_refs=refs,
                requirement_refs=list(dict.fromkeys(ref for test in tests for ref in test.requirement_refs)),
                risk="high" if high_risk else "medium",
                estimated_case_count=len(tests),
                expected_output=(
                    "Observed screens, controls and evidence-backed cases for this coverage area; "
                    "unobserved or unsafe behavior stays clearly deferred."
                ),
                agent="Autopilot planner",
                approval_required=approval,
            )
        )
    requested = list(dict.fromkeys([*analysis.scope.requested_test_types, *grouped.keys()]))
    return AutopilotGenerationPlan(
        plan_id=plan_id or f"plan-{analysis.job_id}",
        job_id=analysis.job_id,
        version=max(1, int(version)),
        status=status if status in {"draft", "pending_review", "approved", "superseded"} else "pending_review",
        target_kind=analysis.target_kind,
        summary=(
            f"{len(analysis.tests)} evidence-scoped case(s) across {len(items)} coverage areas. "
            "Review the scope before live exploration."
        ),
        items=items,
        requested_test_types=requested,
        context_source_count=len(analysis.scope.sources),
        document_section_count=len(analysis.scope.document_sections),
        generated_at=_now(),
    )


def build_application_map(
    *,
    job_id: str,
    target_kind: str,
    target_identity: str | None,
    screens: Iterable[DiscoveredScreen],
    transitions: Iterable[DiscoveredTransition],
    login_observed: bool = False,
    version: int = 1,
) -> AutopilotApplicationMap:
    """Project runtime discovery into a durable map without secret values."""

    screen_list = list(screens)
    transition_list = list(transitions)
    controls = sum(len(screen.controls) for screen in screen_list)
    notes: list[str] = []
    authentication_boundaries: list[str] = []
    validation_behaviors: list[str] = []
    observation_refs: list[str] = []
    confidence_values: list[float] = []
    if login_observed:
        notes.append("A concrete sign-in field/control was observed; authenticated execution remains approval-gated.")
        authentication_boundaries.append("Sign-in boundary observed; credentials remain encrypted and approval-gated.")
    if not screen_list:
        notes.append("No product screen was observed; retry the configured target session before generating deeper cases.")
    if transition_list:
        notes.append(f"{len(transition_list)} observed transition(s) connect the discovered screens.")
        observation_refs.extend(
            transition.observation_ref
            for transition in transition_list
            if transition.observation_ref
        )
    for screen in screen_list:
        if screen.observation_ref:
            observation_refs.append(screen.observation_ref)
        confidence_values.append(float(screen.confidence or 0.0))
        for control in screen.controls:
            if control.observation_ref:
                observation_refs.append(control.observation_ref)
            if control.validation_behavior:
                validation_behaviors.append(control.validation_behavior)
            confidence_values.extend(float(locator.confidence) for locator in control.locators)
    return AutopilotApplicationMap(
        map_id=f"map-{job_id}-v{max(1, int(version))}",
        job_id=job_id,
        target_kind=target_kind if target_kind in {"android", "ios", "web"} else "android",
        target_identity=target_identity,
        version=max(1, int(version)),
        generated_at=_now(),
        login_observed=bool(login_observed),
        screens=screen_list,
        transitions=transition_list,
        controls_count=controls,
        authentication_boundaries=list(dict.fromkeys(authentication_boundaries)),
        validation_behaviors=list(dict.fromkeys(validation_behaviors))[:50],
        observation_refs=list(dict.fromkeys(observation_refs))[:100],
        confidence=(sum(confidence_values) / len(confidence_values) if confidence_values else (1.0 if screen_list else 0.0)),
        coverage_notes=notes,
    )


def normalize_case_signature(value: Any) -> str:
    """Normalize a case/title/step payload for duplicate detection."""

    if isinstance(value, AutopilotTest):
        parts = [value.title, value.objective, *value.steps, *value.expected]
    elif isinstance(value, Mapping):
        parts = [value.get("title"), value.get("objective"), *(value.get("steps") or []), *(value.get("expected") or [])]
    else:
        parts = [value]
    text = " ".join(str(part or "") for part in parts).casefold()
    # IDs, URLs and generated screen hashes should not prevent matching the
    # same business case across runs or between Autopilot and Test Design.
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b(?:tc|case|screen|page)[-_:# ]*[a-z0-9-]+\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def case_fingerprint(value: Any) -> str:
    return hashlib.sha256(normalize_case_signature(value).encode("utf-8")).hexdigest()


def find_duplicate_cases(
    candidates: Iterable[AutopilotTest],
    existing: Iterable[Any] = (),
) -> dict[str, dict[str, Any]]:
    """Return unique/similar/duplicate metadata keyed by candidate ID.

    Exact fingerprints are marked ``duplicate``.  A conservative token-Jaccard
    comparison marks ``similar`` only at 0.86+, avoiding false positives while
    still surfacing likely overlap for user review.
    """

    existing_values = list(existing)
    exact = {case_fingerprint(item): item for item in existing_values}
    existing_tokens = [(item, set(normalize_case_signature(item).split())) for item in existing_values]
    result: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        signature = normalize_case_signature(candidate)
        fingerprint = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        if fingerprint in exact:
            original = exact[fingerprint]
            original_id = getattr(original, "id", None) or (original.get("id") if isinstance(original, Mapping) else None)
            result[candidate.id] = {"status": "duplicate", "duplicate_of": str(original_id) if original_id else None, "fingerprint": fingerprint}
            continue
        tokens = set(signature.split())
        best: tuple[float, Any] | None = None
        for original, other_tokens in existing_tokens:
            union = tokens | other_tokens
            score = len(tokens & other_tokens) / len(union) if union else 1.0
            if best is None or score > best[0]:
                best = (score, original)
        if best and best[0] >= 0.86:
            original = best[1]
            original_id = getattr(original, "id", None) or (original.get("id") if isinstance(original, Mapping) else None)
            result[candidate.id] = {"status": "similar", "duplicate_of": str(original_id) if original_id else None, "similarity": round(best[0], 3), "fingerprint": fingerprint}
        else:
            result[candidate.id] = {"status": "unique", "duplicate_of": None, "fingerprint": fingerprint}
    return result


def coverage_summary(tests: Iterable[AutopilotTest]) -> dict[str, int]:
    """Return stable bucket counts for dashboards and plan review."""

    return dict(Counter(str(test.bucket or "functional") for test in tests))


def build_execution_control_payload(tests: Iterable[AutopilotTest], *, run_id: str | None = None) -> dict[str, Any]:
    """Map grounded cases to a shared execution-control-plane snapshot.

    The existing suite runner can consume its QTX IR immediately; this payload
    gives the normal Test Execution module a durable, framework-neutral handoff
    without embedding secrets or worker-local paths.
    """

    rows = []
    for test in tests:
        rows.append(
            {
                "test_id": test.id,
                "title": test.title,
                "bucket": test.bucket,
                "journey": test.journey,
                "priority": test.priority,
                "requires_auth": test.requires_auth,
                "requires_test_data": test.requires_test_data,
                "readiness": "approval_required" if test.destructive else "discovery_required" if not test.autonomous_candidate else "executable",
                "steps": [{"description": step, "safety": "blocked" if test.destructive else "safe"} for step in test.steps],
                "provenance": [item.model_dump(mode="json") for item in test.provenance],
            }
        )
    return {"schema_version": "qtx-execution-control/1.0", "run_id": run_id, "tests": rows, "total": len(rows)}

