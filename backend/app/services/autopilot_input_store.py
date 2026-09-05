"""Secure storage and bounded generation for Autopilot checkpoint inputs.

The checkpoint UI may collect a value, but this service is the only place that
handles it. Values are encrypted before the database session is committed and
metadata is the only representation copied into a job manifest or response.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Optional
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models.autopilot_input import AutopilotInputRecord
from app.database.models.autopilot_job import AutopilotJob
from app.schemas.autopilot import (
    AutopilotInputDecision,
    AutopilotInputRequest,
    AutopilotInputSubmission,
    AutopilotRandomSpec,
    AutopilotSavedInput,
)


class AutopilotInputStoreError(ValueError):
    """A safe, user-facing validation error with no secret values attached."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fernet(settings: Settings) -> Fernet:
    key_material = (settings.AUTOPILOT_INPUT_ENCRYPTION_KEY or settings.JWT_SECRET or "").strip()
    if not key_material or key_material == "CHANGE_ME_IN_ENV":
        raise AutopilotInputStoreError("Secure input storage is not configured for this environment.")
    # Accept a real Fernet key, otherwise derive a stable key from the existing
    # deployment secret. This permits a zero-downtime migration while allowing
    # operators to rotate to a dedicated key later.
    try:
        return Fernet(key_material.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        digest = hashlib.sha256(key_material.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def _scope_key(job: AutopilotJob) -> str:
    return (job.surface_key or job.job_id or "autopilot").strip()[:128]


def _expiry(settings: Settings, save_for_reuse: bool) -> datetime:
    if save_for_reuse:
        return _now() + timedelta(days=settings.AUTOPILOT_INPUT_SAVED_TTL_DAYS)
    return _now() + timedelta(seconds=settings.AUTOPILOT_INPUT_SESSION_TTL_SECONDS)


def _validate_generator(request: AutopilotInputRequest, spec: Optional[AutopilotRandomSpec]) -> AutopilotRandomSpec:
    if spec is None:
        raise AutopilotInputStoreError("Choose a random-data generator before continuing.")
    if request.category in {"credential", "approval", "acceptance", "integration"} or request.field_type in {"password", "otp", "credential"}:
        raise AutopilotInputStoreError("Random data is available only for non-sensitive test-data fields.")
    if spec.minimum is not None and spec.maximum is not None and spec.minimum > spec.maximum:
        raise AutopilotInputStoreError("The random-data minimum cannot be greater than its maximum.")
    if spec.kind in {"number", "amount"} and spec.minimum is None and spec.maximum is None:
        # Keep generated financial fixtures bounded and deterministic enough for
        # a safe test run when the user leaves the range blank.
        return spec.model_copy(update={"minimum": 0, "maximum": 100000})
    return spec


def generate_synthetic_value(spec: AutopilotRandomSpec) -> str:
    """Generate a bounded fixture in memory; callers encrypt it immediately."""
    rng = random.Random(spec.seed)  # None uses OS entropy; a seed is never a secret.
    if spec.kind in {"number", "amount"}:
        minimum = spec.minimum if spec.minimum is not None else 0
        maximum = spec.maximum if spec.maximum is not None else 100000
        value = rng.uniform(minimum, maximum)
        return f"{value:.2f}" if spec.kind == "amount" else f"{value:.6f}".rstrip("0").rstrip(".")
    if spec.kind == "digits":
        return "".join(rng.choice(string.digits) for _ in range(spec.length))
    if spec.kind == "email":
        token = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(max(6, min(spec.length, 32))))
        return f"qtxpert+{token}@example.test"
    if spec.kind == "phone":
        return "+9715" + "".join(rng.choice(string.digits) for _ in range(max(7, min(spec.length, 9))))
    if spec.kind == "date":
        return _now().date().isoformat()
    alphabet = string.ascii_letters + string.digits + " -_"
    return "".join(rng.choice(alphabet) for _ in range(spec.length)).strip() or "test-data"


def _metadata(record: AutopilotInputRecord) -> AutopilotSavedInput:
    spec = record.generator_spec or {}
    return AutopilotSavedInput(
        key=record.input_key,
        label=record.label,
        category=record.category,  # type: ignore[arg-type]
        decision=record.decision,  # type: ignore[arg-type]
        save_for_reuse=record.save_for_reuse,
        has_value=bool(record.encrypted_value or record.generator_spec),
        generator_kind=spec.get("kind"),
        source=record.source if record.source in {"plan", "runtime", "user"} else "user",
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
        expires_at=record.expires_at.isoformat() if record.expires_at else None,
    )


async def list_metadata(
    db: AsyncSession,
    owner_id: UUID,
    project_id: Optional[UUID],
    surface_key: str,
) -> list[AutopilotSavedInput]:
    query = select(AutopilotInputRecord).where(
        AutopilotInputRecord.owner_id == owner_id,
        AutopilotInputRecord.surface_key == surface_key,
        or_(AutopilotInputRecord.expires_at.is_(None), AutopilotInputRecord.expires_at > _now()),
    )
    if project_id is None:
        query = query.where(AutopilotInputRecord.project_id.is_(None))
    else:
        query = query.where(AutopilotInputRecord.project_id == project_id)
    rows = (await db.scalars(query.order_by(AutopilotInputRecord.updated_at.desc()))).all()
    return [_metadata(row) for row in rows]


async def apply_submissions(
    db: AsyncSession,
    settings: Settings,
    job: AutopilotJob,
    submissions: Iterable[AutopilotInputSubmission],
    requests: Mapping[str, AutopilotInputRequest],
) -> tuple[dict[str, AutopilotInputDecision], list[AutopilotSavedInput]]:
    """Validate, encrypt and upsert checkpoint decisions for one job surface."""
    submissions = list(submissions)
    if len(submissions) > 50:
        raise AutopilotInputStoreError("At most 50 checkpoint inputs can be submitted at once.")
    if not submissions:
        return {}, await list_metadata(db, job.owner_id, job.project_id, _scope_key(job))

    key_set = {str(key).strip() for key in requests}
    unknown = [item.key for item in submissions if item.key not in key_set]
    if unknown:
        raise AutopilotInputStoreError("One or more checkpoint inputs are no longer part of this analysis. Refresh and try again.")
    cipher = _fernet(settings)
    scope = _scope_key(job)
    existing_rows = (
        await db.scalars(
            select(AutopilotInputRecord).where(
                AutopilotInputRecord.owner_id == job.owner_id,
                AutopilotInputRecord.surface_key == scope,
                AutopilotInputRecord.input_key.in_(key_set),
            )
        )
    ).all()
    existing = {row.input_key: row for row in existing_rows}
    decisions: dict[str, AutopilotInputDecision] = {}
    for item in submissions:
        request = requests[item.key]
        decision = item.decision
        if decision == "provide":
            if item.value is None or not item.value.strip():
                raise AutopilotInputStoreError(f"Enter a value for {request.label}, or choose Skip.")
            if len(item.value) > 4000:
                raise AutopilotInputStoreError(f"The value for {request.label} is too long.")
            if request.credential_bundle and item.value.lstrip().startswith("{"):
                # The UI submits the User ID and password as one encrypted
                # bundle so neither value is ever returned in a response. Keep
                # accepting a vault reference string for older API clients.
                try:
                    bundle = json.loads(item.value)
                except json.JSONDecodeError as exc:
                    raise AutopilotInputStoreError(
                        "Enter both the UAT user ID/email and password, or provide a credential-set reference."
                    ) from exc
                if not isinstance(bundle, dict) or not str(bundle.get("username") or "").strip() or not str(bundle.get("password") or ""):
                    raise AutopilotInputStoreError(
                        "Enter both the UAT user ID/email and password before continuing."
                    )
            encrypted = cipher.encrypt(item.value.encode("utf-8")).decode("ascii")
            generator_spec = None
        elif decision == "random":
            spec = _validate_generator(request, item.random_spec)
            encrypted = cipher.encrypt(generate_synthetic_value(spec).encode("utf-8")).decode("ascii")
            generator_spec = spec.model_dump(mode="json")
        elif decision == "reuse":
            row = existing.get(item.key)
            if row is None or not row.save_for_reuse or (row.expires_at and row.expires_at <= _now()) or not row.encrypted_value:
                raise AutopilotInputStoreError(f"No saved value is available for {request.label}. Choose Enter, Random or Skip.")
            encrypted = row.encrypted_value
            generator_spec = row.generator_spec
        else:  # skip
            encrypted = None
            generator_spec = None

        row = existing.get(item.key)
        if row is None:
            row = AutopilotInputRecord(
                owner_id=job.owner_id,
                project_id=job.project_id,
                job_id=job.job_id,
                surface_key=scope,
                input_key=item.key,
                label=request.label[:240],
                category=request.category,
                source=request.source or "user",
            )
            db.add(row)
            existing[item.key] = row
        row.job_id = job.job_id
        row.label = request.label[:240]
        row.category = request.category
        row.decision = decision
        row.save_for_reuse = bool(item.save_for_reuse) if decision in {"provide", "random"} else bool(row.save_for_reuse and decision == "reuse")
        row.encrypted_value = encrypted
        row.generator_spec = generator_spec
        row.expires_at = _expiry(settings, row.save_for_reuse)
        row.last_used_at = _now() if decision == "reuse" else row.last_used_at
        decisions[item.key] = decision

    await db.flush()
    return decisions, await list_metadata(db, job.owner_id, job.project_id, scope)


async def resolve_value(
    db: AsyncSession,
    settings: Settings,
    owner_id: UUID,
    project_id: Optional[UUID],
    surface_key: str,
    input_key: str,
) -> Optional[str]:
    """Resolve one value inside a runner without ever returning it to HTTP."""
    query = select(AutopilotInputRecord).where(
        AutopilotInputRecord.owner_id == owner_id,
        AutopilotInputRecord.surface_key == surface_key,
        AutopilotInputRecord.input_key == input_key,
        AutopilotInputRecord.encrypted_value.is_not(None),
        or_(AutopilotInputRecord.expires_at.is_(None), AutopilotInputRecord.expires_at > _now()),
    )
    if project_id is None:
        query = query.where(AutopilotInputRecord.project_id.is_(None))
    else:
        query = query.where(AutopilotInputRecord.project_id == project_id)
    row = await db.scalar(query.order_by(AutopilotInputRecord.updated_at.desc()))
    if row is None or not row.encrypted_value:
        return None
    try:
        value = _fernet(settings).decrypt(row.encrypted_value.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        return None
    row.last_used_at = _now()
    return value
