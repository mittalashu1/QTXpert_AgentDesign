"""Resolve scoped fixture bindings and verify independent UAT ledger evidence."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from xml.etree import ElementTree
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from uuid import UUID

from cryptography.fernet import InvalidToken
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models.autopilot_input import AutopilotInputRecord
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.execution import ExecutionResult, ExecutionRun, ResultStatus
from app.schemas.authored_execution import AuthoredAutomation, FixtureBinding, LedgerExpectation, SignedLedgerEvidence
from app.services.autopilot_input_store import AutopilotInputStoreError, _fernet

REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{4,128}")


class FixtureUnavailable(ValueError):
    pass


def origin_of(url: str) -> tuple[str, str | None, int | None]:
    target = urlparse(url)
    return target.scheme, target.hostname, target.port or {"https": 443, "http": 80}.get(target.scheme)


def authored_url(base_url: str, path: str) -> str:
    joined = urljoin(base_url, path)
    if not base_url or origin_of(joined) != origin_of(base_url):
        raise ValueError("Authored navigation must stay on the selected web origin.")
    if urlparse(joined).username is not None:
        raise ValueError("Authored navigation requires a URL without embedded credentials.")
    return joined


def fixture_keys(automation: AuthoredAutomation) -> set[str]:
    return {step.input_key for step in automation.steps if step.input_key}


def native_text_visible(source: str, expected: str) -> bool:
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError:
        return False
    return any(
        node.get("displayed") != "false" and node.get("visible") != "false"
        and node.get("password") != "true"
        and expected in {node.get("text"), node.get("content-desc"), node.get("label")}
        for node in root.iter()
    )


async def scoped_fixtures(
    db: AsyncSession,
    *,
    owner_id: UUID,
    project_id: UUID,
    target_kind: str,
    app_asset_id: UUID | None,
    base_url: str | None,
    record_ids: set[UUID] | None = None,
) -> list[AutopilotInputRecord]:
    if target_kind == "web" and base_url:
        scope = func.rtrim(AutopilotJob.target_url, "/") == base_url.rstrip("/")
    elif target_kind in {"android", "ios"} and app_asset_id:
        scope = AutopilotJob.repository_asset_id == app_asset_id
    else:
        return []
    query = select(AutopilotInputRecord).join(
        AutopilotJob, AutopilotJob.job_id == AutopilotInputRecord.job_id,
    ).where(
        AutopilotInputRecord.owner_id == owner_id,
        AutopilotInputRecord.project_id == project_id,
        AutopilotInputRecord.save_for_reuse.is_(True),
        AutopilotInputRecord.encrypted_value.is_not(None),
        AutopilotInputRecord.category.in_(("credential", "test_data")),
        or_(
            AutopilotInputRecord.expires_at.is_(None),
            AutopilotInputRecord.expires_at > datetime.now(timezone.utc),
        ),
        AutopilotJob.owner_id == owner_id,
        AutopilotJob.project_id == project_id,
        AutopilotJob.target_kind == target_kind,
        scope,
    )
    if record_ids is not None:
        if not record_ids:
            return []
        query = query.where(AutopilotInputRecord.id.in_(record_ids))
        return list(await db.scalars(query))

    # A reusable input can have several run-specific bindings. Offer the
    # latest binding in the picker and still honor explicitly saved plan IDs.
    latest = query.with_only_columns(AutopilotInputRecord.id).distinct(
        AutopilotInputRecord.surface_key, AutopilotInputRecord.input_key,
    ).order_by(
        AutopilotInputRecord.surface_key, AutopilotInputRecord.input_key,
        AutopilotInputRecord.updated_at.desc(), AutopilotInputRecord.id.desc(),
    ).subquery()
    query = select(AutopilotInputRecord).join(latest, latest.c.id == AutopilotInputRecord.id)
    return list(await db.scalars(query.order_by(AutopilotInputRecord.updated_at.desc()).limit(200)))


def allowed_fixture_parts(row: AutopilotInputRecord) -> list[str]:
    return ["username", "password"] if row.input_key == "credential_reference" else ["value"]


async def prepare_authored_cases(
    db: AsyncSession, settings: Settings, run: ExecutionRun, pending: list[ExecutionResult],
) -> dict[UUID, dict]:
    """Resolve only frozen bindings for a queued run, without persisting plaintext."""
    available_ids = {
        UUID(binding["record_id"]) for result in pending
        for binding in (result.execution_spec or {}).get("bindings", {}).values()
    }
    scoped = await scoped_fixtures(
        db, owner_id=run.requested_by_id, project_id=run.project_id, target_kind=run.target_kind,
        app_asset_id=run.app_asset_id, base_url=run.base_url, record_ids=available_ids,
    )
    by_id = {item.id: item for item in scoped}
    decoded: dict[UUID, str] = {}
    prepared = {}
    for result in pending:
        spec = result.execution_spec or {}
        if not spec.get("automation"):
            continue
        try:
            automation = AuthoredAutomation.model_validate(spec["automation"])
            values = {}
            for key in sorted(fixture_keys(automation)):
                payload = spec.get("bindings", {}).get(key)
                if payload is None:
                    raise FixtureUnavailable(f"Bind the saved Test Data for {key}.")
                binding = FixtureBinding.model_validate(payload)
                row = by_id.get(binding.record_id)
                if row is None or binding.part not in allowed_fixture_parts(row):
                    raise FixtureUnavailable(f"Saved Test Data for {key} is unavailable for the selected build or URL.")
                try:
                    raw = decoded.get(row.id)
                    if raw is None:
                        raw = _fernet(settings).decrypt(row.encrypted_value.encode("ascii")).decode()
                        decoded[row.id] = raw
                    value = raw if binding.part == "value" else json.loads(raw).get(binding.part)
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError
                except (InvalidToken, ValueError, UnicodeError, AttributeError, AutopilotInputStoreError):
                    raise FixtureUnavailable(f"Saved Test Data for {key} could not be read.") from None
                row.last_used_at = datetime.now(timezone.utc)
                values[key] = value
            steps = []
            for step in automation.steps:
                action = step.model_dump(exclude_none=True, exclude={"input_key"})
                if step.input_key:
                    action["value"] = values[step.input_key]
                steps.append(action)
            prepared[result.id] = {"authored_steps": steps, "uses_fixture": bool(values), "business_case": automation.outcome is not None}
        except FixtureUnavailable as exc:
            result.status = ResultStatus.BLOCKED
            result.error_message = str(exc)
            result.evidence = {"preflight": "fixture_unavailable"}
    return prepared


def record_ui_outcome(result: ExecutionResult, reference: str | None) -> None:
    spec = (result.execution_spec or {}).get("automation") or {}
    if result.status != ResultStatus.PASSED or not spec.get("outcome"):
        return
    result.status = ResultStatus.BLOCKED
    result.error_message = "The UI assertion passed. Import signed UAT ledger evidence to determine the business verdict."
    reference = (reference or "").strip()
    evidence = {**(result.evidence or {}), "ui_assertion": "passed"}
    if not REFERENCE_PATTERN.fullmatch(reference):
        result.error_message = "The UI assertion passed but a usable receipt or attempt reference was unavailable."
        result.evidence = {**evidence, "business_verification": "reference_missing"}
        return
    result.evidence = {
        **evidence,
        "business_verification": "awaiting_ledger",
        "business_reference": reference,
        "expected_business_outcome": spec["outcome"],
    }


def verified_ledger_outcome(
    *, settings: Settings, run: ExecutionRun, result: ExecutionResult, evidence: SignedLedgerEvidence,
) -> tuple[bool, dict]:
    key = (settings.UAT_LEDGER_VERIFICATION_KEY or "").strip()
    if len(key) < 32:
        raise ValueError("Configure the UAT ledger verification key before accepting evidence.")
    payload = evidence.model_dump(mode="json", exclude={"signature"})
    signed = {
        "schema": "qtx-uat-ledger/1",
        "project_id": str(run.project_id),
        "run_id": str(run.id),
        "result_id": str(result.id),
        "evidence": payload,
    }
    canonical = json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if not hmac.compare_digest(hmac.new(key.encode(), canonical, hashlib.sha256).hexdigest(), evidence.signature):
        raise ValueError("The UAT ledger evidence signature is invalid for this result.")
    if (
        run.started_at is None or run.completed_at is None
        or evidence.decision_at < run.started_at
        or evidence.decision_at > run.completed_at + timedelta(minutes=5)
        or evidence.observed_at < evidence.decision_at
        or evidence.observed_at > datetime.now(timezone.utc) + timedelta(minutes=5)
    ):
        raise ValueError("The signed observation must come from this execution window.")
    current = result.evidence or {}
    if evidence.reference != current.get("business_reference"):
        raise ValueError("The signed evidence must match the reference captured by the runner.")
    expected = LedgerExpectation.model_validate(current["expected_business_outcome"])
    if (
        evidence.operation != expected.operation or evidence.account_alias != expected.account_alias
        or evidence.seed_reference != expected.seed_reference or evidence.cleanup_reference != expected.cleanup_reference
    ):
        raise ValueError("The signed ledger record must match the planned operation and UAT fixture references.")
    matches = (
        evidence.decision == expected.outcome and evidence.amount_minor == expected.amount_minor
        and evidence.currency == expected.currency
        and evidence.posted_count == (1 if expected.outcome == "posted" else 0)
    )
    return matches, {
        **payload,
        "signature": evidence.signature,
        "digest": hashlib.sha256(canonical).hexdigest(),
        "schema": signed["schema"],
    }
