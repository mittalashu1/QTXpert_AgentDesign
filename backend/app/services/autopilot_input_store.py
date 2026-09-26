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
from sqlalchemy import and_, or_, select
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


def _checkpoint_label_identity(label: str) -> str:
    """Normalize user-facing field labels for a safe same-surface rebind."""
    return " ".join(str(label or "").split()).casefold()


def _reusable_runtime_record(record: Optional[AutopilotInputRecord]) -> bool:
    """Return whether a stored runtime value is safe to reuse or remap."""
    if (
        record is None
        or record.source != "runtime"
        or not record.save_for_reuse
        or not record.encrypted_value
    ):
        return False
    expires_at = record.expires_at
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > _now()


def _runtime_record_matches_request(
    record: AutopilotInputRecord,
    request: AutopilotInputRequest,
) -> bool:
    """Match saved ciphertext to one observed field without relying on volatile IDs."""
    return (
        request.source == "runtime"
        and record.source == "runtime"
        and record.category == request.category
        and _checkpoint_label_identity(record.label) == _checkpoint_label_identity(request.label)
    )


def _reconcile_runtime_reuse_submissions(
    submissions: Iterable[AutopilotInputSubmission],
    requests: Mapping[str, AutopilotInputRequest],
    stored_rows: Iterable[AutopilotInputRecord],
) -> tuple[list[AutopilotInputSubmission], dict[str, AutopilotInputRecord]]:
    """Rebind a saved runtime value only when its observed field is unambiguous.

    Runtime screen/control IDs can change after a fresh mobile discovery.  A
    stale *reuse* decision is recoverable only from an encrypted, reusable
    row in the same owner/project/surface query, and only when exactly one
    current runtime request has the same source, category and human field
    label.  Direct values, random recipes, ambiguous matches and unmatched
    values remain rejected by the normal stale-key validator.
    """
    submitted = list(submissions)
    request_keys = {str(key).strip() for key in requests}
    rows_by_key = {row.input_key: row for row in stored_rows}
    accepted: list[AutopilotInputSubmission] = []
    reusable_rows: dict[str, AutopilotInputRecord] = {}
    used_request_keys: set[str] = set()

    for item in submitted:
        if item.key in request_keys:
            accepted.append(item)
            used_request_keys.add(item.key)
            if item.decision == "reuse":
                request = requests[item.key]
                exact = rows_by_key.get(item.key)
                if (
                    _reusable_runtime_record(exact)
                    and exact.category == request.category
                    and exact.source == request.source
                ):
                    reusable_rows[item.key] = exact
                else:
                    aliases = [
                        row for row in stored_rows
                        if row.input_key != item.key
                        and _reusable_runtime_record(row)
                        and _runtime_record_matches_request(row, request)
                    ]
                    if len(aliases) == 1:
                        reusable_rows[item.key] = aliases[0]
            continue

        stale_skip_only = (
            item.decision == "skip"
            and not item.value
            and not item.save_for_reuse
            and item.random_spec is None
        )
        if stale_skip_only:
            continue

        if item.decision == "reuse":
            saved_row = rows_by_key.get(item.key)
            if _reusable_runtime_record(saved_row):
                matches = [
                    request for request in requests.values()
                    if _runtime_record_matches_request(saved_row, request)
                ]
                if len(matches) == 1 and matches[0].key not in used_request_keys:
                    request = matches[0]
                    accepted.append(item.model_copy(update={"key": request.key}))
                    reusable_rows[request.key] = saved_row
                    used_request_keys.add(request.key)
                    continue

        raise AutopilotInputStoreError(
            "One or more checkpoint inputs are no longer part of this analysis. Refresh and try again."
        )

    return accepted, reusable_rows


def _current_submissions(
    submissions: Iterable[AutopilotInputSubmission],
    requests: Mapping[str, AutopilotInputRequest],
) -> list[AutopilotInputSubmission]:
    """Discard only obsolete skip-only drafts from a refreshed checkpoint.

    A stale draft cannot write or reuse a value. It is safe to ignore only an
    old Skip with no value, save flag, or random-data configuration.
    """
    accepted: list[AutopilotInputSubmission] = []
    known_keys = {str(key).strip() for key in requests}
    for item in submissions:
        if item.key in known_keys:
            accepted.append(item)
            continue
        stale_skip_only = (
            item.decision == "skip"
            and not item.value
            and not item.save_for_reuse
            and item.random_spec is None
        )
        if not stale_skip_only:
            raise AutopilotInputStoreError(
                "One or more checkpoint inputs are no longer part of this analysis. Refresh and try again."
            )
    return accepted


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
    scope = _scope_key(job)
    if not submissions:
        return {}, await list_metadata(db, job.owner_id, job.project_id, scope)

    key_set = {str(key).strip() for key in requests}
    submitted_keys = {str(item.key).strip() for item in submissions}
    lookup_keys = key_set | submitted_keys
    runtime_requests = [request for request in requests.values() if request.source == "runtime"]
    runtime_labels = {request.label[:240] for request in runtime_requests}
    runtime_categories = {request.category for request in runtime_requests}
    row_filters = []
    if lookup_keys:
        row_filters.append(AutopilotInputRecord.input_key.in_(lookup_keys))
    if runtime_labels and runtime_categories:
        row_filters.append(
            and_(
                AutopilotInputRecord.source == "runtime",
                AutopilotInputRecord.category.in_(runtime_categories),
                AutopilotInputRecord.label.in_(runtime_labels),
                AutopilotInputRecord.save_for_reuse.is_(True),
                AutopilotInputRecord.encrypted_value.is_not(None),
                or_(
                    AutopilotInputRecord.expires_at.is_(None),
                    AutopilotInputRecord.expires_at > _now(),
                ),
            )
        )

    # Reuse is deliberately scoped to the exact owner *and project*.  A
    # surface key identifies the profile/target/build, but it is not a tenant
    # boundary: two projects can legitimately use the same profile and APK
    # digest.  Without this predicate an upsert could read a saved credential
    # from another project and attach it to the current job.
    project_scope = (
        AutopilotInputRecord.project_id == job.project_id
        if job.project_id is not None
        else AutopilotInputRecord.project_id.is_(None)
    )
    existing_rows = (
        await db.scalars(
            select(AutopilotInputRecord).where(
                AutopilotInputRecord.owner_id == job.owner_id,
                project_scope,
                AutopilotInputRecord.surface_key == scope,
                or_(*row_filters),
            )
        )
    ).all()
    existing = {row.input_key: row for row in existing_rows}
    submissions, reusable_rows = _reconcile_runtime_reuse_submissions(
        submissions,
        requests,
        existing_rows,
    )
    submissions = _current_submissions(submissions, requests)
    if not submissions:
        return {}, await list_metadata(db, job.owner_id, job.project_id, scope)

    cipher = _fernet(settings)
    decisions: dict[str, AutopilotInputDecision] = {}
    for item in submissions:
        request = requests[item.key]
        decision = item.decision
        if decision == "provide":
            # Approval is a boolean checkpoint, not a data field.  The UI can
            # submit the decision without inventing a placeholder value; the
            # setup profile persists the actual approval flag separately.
            approval_only = request.category == "approval" and request.key == "safe_authentication_approved"
            if approval_only:
                encrypted = None
                generator_spec = None
            else:
                if item.value is None or not item.value.strip():
                    raise AutopilotInputStoreError(f"Enter a value for {request.label}, or choose Skip.")
                if len(item.value) > 4000:
                    raise AutopilotInputStoreError(f"The value for {request.label} is too long.")
            if not approval_only and request.credential_bundle and item.value.lstrip().startswith("{"):
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
            if not approval_only:
                encrypted = cipher.encrypt(item.value.encode("utf-8")).decode("ascii")
                generator_spec = None
        elif decision == "random":
            spec = _validate_generator(request, item.random_spec)
            encrypted = cipher.encrypt(generate_synthetic_value(spec).encode("utf-8")).decode("ascii")
            generator_spec = spec.model_dump(mode="json")
        elif decision == "reuse":
            row = existing.get(item.key) or reusable_rows.get(item.key)
            if row is None or not row.save_for_reuse or (row.expires_at and row.expires_at <= _now()) or not row.encrypted_value:
                raise AutopilotInputStoreError(f"No saved value is available for {request.label}. Choose Enter, Random or Skip.")
            encrypted = row.encrypted_value
            generator_spec = row.generator_spec
        else:  # skip
            encrypted = None
            generator_spec = None

        row = existing.get(item.key) or reusable_rows.get(item.key)
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
        elif row.project_id != job.project_id:
            # Defensive guard for rows created before the project predicate
            # was introduced.  Never mutate or reuse a cross-project record.
            raise AutopilotInputStoreError(
                "The saved input belongs to a different project. Choose Enter, Random or Skip."
            )
        if row.input_key != item.key:
            # Move only the exact, uniquely matched encrypted runtime record
            # after the user explicitly chose Reuse. The next checkpoint read
            # and in-process runner will then resolve the current key directly.
            row.input_key = item.key
        row.job_id = job.job_id
        row.label = request.label[:240]
        row.category = request.category
        row.decision = decision
        row.save_for_reuse = bool(item.save_for_reuse) if decision in {"provide", "random"} else bool(row.save_for_reuse and decision == "reuse")
        row.encrypted_value = encrypted
        row.generator_spec = generator_spec
        row.source = request.source or "user"
        row.expires_at = _expiry(settings, row.save_for_reuse)
        row.last_used_at = _now() if decision == "reuse" else row.last_used_at
        existing[item.key] = row
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
