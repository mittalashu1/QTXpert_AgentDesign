"""Safe, reviewable retention for generated QTXpert data.

The product stores reusable source material (documents and APK/IPA builds) in
the Upload Repository and stores generated artifacts/results in relational
tables.  This service only removes generated history that is both older than
the configured cutoff and outside the newest-N window for its owner/project
surface.  Source assets are never selected by the default policy.

Deletion is intentionally a two-step operation: callers can run a dry-run
preview, then explicitly request execution.  Active jobs/runs and generated
records still needed by retained execution evidence are protected.
"""
from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models.autopilot_execution import AutopilotExecution
from app.database.models.autopilot_job import AutopilotJob
from app.database.models.document_intelligence import DocumentAnalysisRun, DocumentFinding
from app.database.models.execution import ExecutionResult, ExecutionRun
from app.database.models.execution_plan import ExecutionPlan
from app.database.models.generation_run import GenerationRun
from app.database.models.test_case import TestCase
from app.database.models.uploaded_asset import UploadedAsset
from app.services.object_storage import ObjectStorageService
from app.services.upload_repository import (
    UploadRepositoryService,
    UploadRepositoryStorageUnavailable,
)

logger = logging.getLogger(__name__)

EPHEMERAL_ASSET_CATEGORIES = frozenset(
    {"test_data", "autopilot_evidence", "execution_evidence"}
)
ACTIVE_GENERATION_STATUSES = frozenset(
    {"pending", "normalizing", "analyzing", "generating_scenarios", "generating_test_cases", "risk_analysis"}
)
ACTIVE_EXECUTION_STATUSES = frozenset({"queued", "running"})
ACTIVE_AUTOPILOT_STATUSES = frozenset({"uploaded", "analyzing", "running", "queued"})
ACTIVE_DOCUMENT_STATUSES = frozenset({"pending", "running", "analyzing", "processing"})


@dataclass(slots=True)
class RetentionSummary:
    """Machine- and human-readable outcome of a retention pass."""

    cutoff: datetime
    keep_latest: int
    dry_run: bool
    candidates: dict[str, int] = field(default_factory=dict)
    protected: dict[str, int] = field(default_factory=dict)
    deleted: dict[str, int] = field(default_factory=dict)
    deleted_bytes: int = 0
    local_paths_removed: int = 0
    storage_failures: list[str] = field(default_factory=list)
    local_path_failures: list[str] = field(default_factory=list)

    @property
    def candidate_total(self) -> int:
        return sum(self.candidates.values())

    @property
    def deleted_total(self) -> int:
        return sum(self.deleted.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "cutoff": self.cutoff.isoformat(),
            "keep_latest": self.keep_latest,
            "dry_run": self.dry_run,
            "candidates": dict(self.candidates),
            "protected": dict(self.protected),
            "deleted": dict(self.deleted),
            "candidate_total": self.candidate_total,
            "deleted_total": self.deleted_total,
            "deleted_bytes": self.deleted_bytes,
            "local_paths_removed": self.local_paths_removed,
            "storage_failures": list(self.storage_failures),
            "local_path_failures": list(self.local_path_failures),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _ranked_ids(
    db: AsyncSession,
    model: Any,
    partition_by: Any,
    cutoff: datetime,
    keep_latest: int,
) -> list[UUID]:
    """Return IDs older than cutoff and outside newest-N per partition.

    The cutoff is applied after the window function so records created within
    the retention window never become candidates, and the newest-N guarantee
    is evaluated against the complete history rather than only old rows.
    """
    rank = func.row_number().over(
        partition_by=partition_by,
        order_by=(model.created_at.desc(), model.id.desc()),
    ).label("retention_rank")
    ranked = select(
        model.id.label("id"),
        model.created_at.label("created_at"),
        rank,
    ).subquery()
    result = await db.scalars(
        select(ranked.c.id).where(
            ranked.c.created_at < cutoff,
            ranked.c.retention_rank > keep_latest,
        )
    )
    return list(result.all())


async def _remove_active_ids(
    db: AsyncSession,
    model: Any,
    ids: Sequence[UUID],
    active_statuses: Iterable[str],
) -> tuple[list[UUID], int]:
    if not ids:
        return [], 0
    active = set(
        await db.scalars(
            select(model.id).where(
                model.id.in_(ids),
                model.status.in_(list(active_statuses)),
            )
        )
    )
    return [item for item in ids if item not in active], len(active)


async def _generation_runs_with_execution_results(
    db: AsyncSession,
    ids: Sequence[UUID],
    execution_run_candidates: Sequence[UUID],
) -> set[UUID]:
    if not ids:
        return set()
    retained_execution_filter = (
        ~ExecutionResult.execution_run_id.in_(execution_run_candidates)
        if execution_run_candidates
        else True
    )
    rows = await db.scalars(
        select(TestCase.generation_run_id)
        .join(ExecutionResult, ExecutionResult.test_case_id == TestCase.id)
        .where(TestCase.generation_run_id.in_(ids), retained_execution_filter)
        .distinct()
    )
    return set(rows.all())


async def _load_rows(db: AsyncSession, model: Any, ids: Sequence[UUID]) -> list[Any]:
    if not ids:
        return []
    return list((await db.scalars(select(model).where(model.id.in_(ids)))).all())


def _as_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def _ids_from_json(value: Any) -> set[UUID]:
    """Extract asset IDs from flexible evidence/metadata JSON safely."""
    found: set[UUID] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if "asset" in str(key).lower() and "id" in str(key).lower():
                if isinstance(item, (list, tuple, set)):
                    for candidate in item:
                        parsed = _as_uuid(candidate)
                        if parsed:
                            found.add(parsed)
                else:
                    parsed = _as_uuid(item)
                    if parsed:
                        found.add(parsed)
            found.update(_ids_from_json(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_ids_from_json(item))
    return found


async def _retained_asset_references(
    db: AsyncSession,
    *,
    autopilot_execution_candidates: Sequence[UUID],
    autopilot_job_candidates: Sequence[UUID],
    execution_run_candidates: Sequence[UUID],
    document_run_candidates: Sequence[UUID],
) -> set[UUID]:
    """Find ephemeral assets still needed by records that will remain."""
    references: set[UUID] = set()

    auto_query = select(AutopilotExecution).where(
        ~AutopilotExecution.id.in_(autopilot_execution_candidates)
        if autopilot_execution_candidates
        else True
    )
    for row in (await db.scalars(auto_query)).all():
        for value in (
            row.repository_asset_id,
            row.screenshot_asset_id,
            row.page_source_asset_id,
        ):
            parsed = _as_uuid(value)
            if parsed:
                references.add(parsed)
        references.update(_ids_from_json(row.evidence))

    job_query = select(AutopilotJob).where(
        ~AutopilotJob.id.in_(autopilot_job_candidates)
        if autopilot_job_candidates
        else True
    )
    for row in (await db.scalars(job_query)).all():
        parsed = _as_uuid(row.repository_asset_id)
        if parsed:
            references.add(parsed)
        references.update(_ids_from_json(row.document_asset_ids))
        # Runtime discovery and safe-suite results are stored as JSON on the
        # job.  They contain screenshot/page-source evidence IDs, so a
        # retained job must keep those generated assets as well.  Omitting
        # these fields leaves report tabs pointing at deleted evidence after a
        # retention sweep and causes noisy 404s when the UI renders them.
        references.update(_ids_from_json(row.discovery))
        references.update(_ids_from_json(row.suite_execution))
        references.update(_ids_from_json(row.analysis))

    run_query = select(ExecutionRun).where(
        ~ExecutionRun.id.in_(execution_run_candidates)
        if execution_run_candidates
        else True
    )
    for row in (await db.scalars(run_query)).all():
        parsed = _as_uuid(row.app_asset_id)
        if parsed:
            references.add(parsed)
        references.update(_ids_from_json(row.target_metadata))

    result_query = select(ExecutionResult).where(
        ~ExecutionResult.execution_run_id.in_(execution_run_candidates)
        if execution_run_candidates
        else True
    )
    for row in (await db.scalars(result_query)).all():
        references.update(_ids_from_json(row.evidence))

    document_query = select(DocumentAnalysisRun).where(
        ~DocumentAnalysisRun.id.in_(document_run_candidates)
        if document_run_candidates
        else True
    )
    for row in (await db.scalars(document_query)).all():
        references.update(_ids_from_json(row.asset_ids))

    finding_query = (
        select(DocumentFinding.asset_id)
        .join(DocumentAnalysisRun, DocumentAnalysisRun.id == DocumentFinding.run_id)
        .where(
            DocumentFinding.asset_id.is_not(None),
            ~DocumentAnalysisRun.id.in_(document_run_candidates)
            if document_run_candidates
            else True,
        )
    )
    for value in (await db.scalars(finding_query)).all():
        parsed = _as_uuid(value)
        if parsed:
            references.add(parsed)
    return references


async def _asset_candidates(
    db: AsyncSession,
    cutoff: datetime,
    keep_latest: int,
    protected_ids: set[UUID],
) -> list[UploadedAsset]:
    """Select only old test/evidence assets outside newest-N per owner/category."""
    rank = func.row_number().over(
        partition_by=(UploadedAsset.owner_id, UploadedAsset.project_id, UploadedAsset.category),
        order_by=(UploadedAsset.created_at.desc(), UploadedAsset.id.desc()),
    ).label("retention_rank")
    ranked = select(
        UploadedAsset.id.label("id"),
        UploadedAsset.created_at.label("created_at"),
        rank,
    ).where(
        UploadedAsset.category.in_(EPHEMERAL_ASSET_CATEGORIES),
    ).subquery()
    ids = list(
        (
            await db.scalars(
                select(ranked.c.id).where(
                    ranked.c.created_at < cutoff,
                    ranked.c.retention_rank > keep_latest,
                )
            )
        ).all()
    )
    ids = [item for item in ids if item not in protected_ids]
    return await _load_rows(db, UploadedAsset, ids)


def _safe_job_path(root: Path, job_id: str) -> Path | None:
    if not re.fullmatch(r"[0-9a-f-]{36}", str(job_id or ""), flags=re.IGNORECASE):
        return None
    root = root.resolve()
    candidate = (root / str(job_id)).resolve()
    if candidate.parent != root:
        return None
    return candidate


def _remove_local_paths(
    settings: Settings,
    *,
    job_ids: Sequence[str],
    execution_rows: Sequence[AutopilotExecution],
    summary: RetentionSummary,
) -> None:
    """Remove disposable Autopilot files without ever escaping its root."""
    root = Path(settings.AUTOPILOT_STORAGE_PATH).resolve()
    for job_id in job_ids:
        target = _safe_job_path(root, job_id)
        if target is None or not target.exists():
            continue
        try:
            shutil.rmtree(target)
            summary.local_paths_removed += 1
        except OSError as exc:
            summary.local_path_failures.append(f"job:{job_id}:{exc}")

    # A retained job may have old execution JSON/evidence directories even when
    # the job itself is kept. Remove only paths named by rows being deleted.
    for row in execution_rows:
        job_dir = _safe_job_path(root, str(row.autopilot_job_id))
        if job_dir is None:
            continue
        execution_id = str(row.id)
        for path in (
            job_dir / "executions" / f"{execution_id}.json",
            job_dir / "evidence" / execution_id,
        ):
            try:
                resolved = path.resolve()
                if resolved != job_dir and job_dir in resolved.parents and resolved.exists():
                    if resolved.is_dir():
                        shutil.rmtree(resolved)
                    else:
                        resolved.unlink()
                    summary.local_paths_removed += 1
            except OSError as exc:
                summary.local_path_failures.append(f"execution:{execution_id}:{exc}")


async def _delete_object_assets(
    assets: Sequence[UploadedAsset],
    settings: Settings,
    summary: RetentionSummary,
) -> list[UploadedAsset]:
    """Delete object-store bytes first; return only rows safe to delete."""
    if not assets:
        return []
    object_store_assets = [
        asset for asset in assets if asset.storage_backend == "object_store"
    ]
    object_assets = [asset for asset in object_store_assets if asset.object_key]
    missing_object_keys = [asset for asset in object_store_assets if not asset.object_key]
    if missing_object_keys:
        summary.storage_failures.extend(
            f"{asset.id}:object-store asset has no object key" for asset in missing_object_keys
        )
    storage: ObjectStorageService | None = None
    if object_assets:
        try:
            storage = UploadRepositoryService._object_storage(settings)
        except UploadRepositoryStorageUnavailable as exc:
            summary.storage_failures.extend(
                f"{asset.id}:{exc}" for asset in object_assets
            )
            return [asset for asset in assets if asset not in object_store_assets]
        if storage is None:
            message = "object-store backend is disabled or not configured"
            summary.storage_failures.extend(
                f"{asset.id}:{message}" for asset in object_assets
            )
            return [asset for asset in assets if asset not in object_store_assets]
    safe: list[UploadedAsset] = []
    for asset in assets:
        if asset in missing_object_keys:
            continue
        if storage is not None and asset in object_assets:
            try:
                await storage.delete(str(asset.object_key))
            except Exception as exc:  # pragma: no cover - provider-specific
                summary.storage_failures.append(f"{asset.id}:{exc}")
                continue
        safe.append(asset)
        summary.deleted_bytes += int(asset.size_bytes or 0)
    return safe


async def cleanup_generated_data(
    db: AsyncSession,
    settings: Settings,
    *,
    dry_run: bool = True,
    now: datetime | None = None,
    days: int | None = None,
    keep_latest: int | None = None,
) -> RetentionSummary:
    """Preview or execute the configured generated-data retention policy.

    ``dry_run=True`` never changes the database or object storage.  A caller
    must explicitly pass ``dry_run=False`` (the admin route additionally
    requires a confirmation flag) to remove anything.
    """
    retention_days = max(1, int(days if days is not None else settings.DATA_RETENTION_DAYS))
    keep = max(0, int(keep_latest if keep_latest is not None else settings.DATA_RETENTION_KEEP_LATEST))
    current = _normalise_datetime(now or _utcnow())
    cutoff = current - timedelta(days=retention_days)
    summary = RetentionSummary(cutoff=cutoff, keep_latest=keep, dry_run=dry_run)

    plan_ids = await _ranked_ids(db, ExecutionPlan, ExecutionPlan.project_id, cutoff, keep)
    plan_ids, protected = await _remove_active_ids(db, ExecutionPlan, plan_ids, ACTIVE_EXECUTION_STATUSES)
    summary.protected["execution_plans_active"] = protected

    execution_ids = await _ranked_ids(db, ExecutionRun, ExecutionRun.project_id, cutoff, keep)
    execution_ids, protected = await _remove_active_ids(db, ExecutionRun, execution_ids, ACTIVE_EXECUTION_STATUSES)
    summary.protected["execution_runs_active"] = protected

    generation_ids = await _ranked_ids(db, GenerationRun, GenerationRun.project_id, cutoff, keep)
    generation_ids, protected = await _remove_active_ids(
        db,
        GenerationRun,
        generation_ids,
        ACTIVE_GENERATION_STATUSES,
    )
    summary.protected["generation_runs_active"] = protected
    active_generation = await _generation_runs_with_execution_results(
        db,
        generation_ids,
        execution_ids,
    )
    generation_ids = [item for item in generation_ids if item not in active_generation]
    summary.protected["generation_runs_with_retained_execution_results"] = len(active_generation)

    job_ids = await _ranked_ids(
        db,
        AutopilotJob,
        (AutopilotJob.owner_id, AutopilotJob.project_id),
        cutoff,
        keep,
    )
    job_ids, protected = await _remove_active_ids(db, AutopilotJob, job_ids, ACTIVE_AUTOPILOT_STATUSES)
    summary.protected["autopilot_jobs_active"] = protected

    autopilot_execution_ids = await _ranked_ids(
        db,
        AutopilotExecution,
        (AutopilotExecution.owner_id, AutopilotExecution.autopilot_job_id),
        cutoff,
        keep,
    )
    autopilot_execution_ids, protected = await _remove_active_ids(
        db,
        AutopilotExecution,
        autopilot_execution_ids,
        ACTIVE_EXECUTION_STATUSES,
    )
    summary.protected["autopilot_executions_active"] = protected

    # A job row owns its Autopilot executions.  Keep a job if one of its
    # executions remains inside the newest-N window; otherwise a database
    # cascade would silently remove retained execution history.
    retained_execution_job_ids = set(
        await db.scalars(
            select(AutopilotExecution.autopilot_job_id).where(
                ~AutopilotExecution.id.in_(autopilot_execution_ids)
                if autopilot_execution_ids
                else True,
            )
        )
    )
    protected_job_ids = set(
        await db.scalars(
            select(AutopilotJob.id).where(
                AutopilotJob.id.in_(job_ids),
                AutopilotJob.id.in_(retained_execution_job_ids),
            )
        )
    ) if job_ids and retained_execution_job_ids else set()
    if protected_job_ids:
        job_ids = [item for item in job_ids if item not in protected_job_ids]
    summary.protected["autopilot_jobs_with_retained_executions"] = len(protected_job_ids)

    document_ids = await _ranked_ids(
        db,
        DocumentAnalysisRun,
        DocumentAnalysisRun.project_id,
        cutoff,
        keep,
    )
    document_ids, protected = await _remove_active_ids(
        db,
        DocumentAnalysisRun,
        document_ids,
        ACTIVE_DOCUMENT_STATUSES,
    )
    summary.protected["document_analysis_runs_active"] = protected

    auto_execution_rows = await _load_rows(db, AutopilotExecution, autopilot_execution_ids)
    job_rows = await _load_rows(db, AutopilotJob, job_ids)
    retained_asset_refs = await _retained_asset_references(
        db,
        autopilot_execution_candidates=autopilot_execution_ids,
        autopilot_job_candidates=job_ids,
        execution_run_candidates=execution_ids,
        document_run_candidates=document_ids,
    )
    assets = (
        await _asset_candidates(db, cutoff, keep, retained_asset_refs)
        if settings.DATA_RETENTION_INCLUDE_EPHEMERAL_ASSETS
        else []
    )

    candidate_map = {
        "generation_runs": len(generation_ids),
        "execution_plans": len(plan_ids),
        "execution_runs": len(execution_ids),
        "autopilot_jobs": len(job_ids),
        "autopilot_executions": len(autopilot_execution_ids),
        "document_analysis_runs": len(document_ids),
        "uploaded_ephemeral_assets": len(assets),
    }
    summary.candidates.update(candidate_map)

    if dry_run:
        return summary

    # Delete object-store bytes before metadata. An uncertain object deletion
    # leaves its metadata in place so a later run can retry safely.
    safe_assets = await _delete_object_assets(assets, settings, summary)

    delete_sets: list[tuple[str, Any, Sequence[UUID]]] = [
        ("generation_runs", GenerationRun, generation_ids),
        ("execution_plans", ExecutionPlan, plan_ids),
        ("execution_runs", ExecutionRun, execution_ids),
        ("autopilot_executions", AutopilotExecution, autopilot_execution_ids),
        # Delete child execution rows before their owning jobs so the summary
        # reflects the actual affected rows instead of a database cascade.
        ("autopilot_jobs", AutopilotJob, job_ids),
        ("document_analysis_runs", DocumentAnalysisRun, document_ids),
        ("uploaded_ephemeral_assets", UploadedAsset, [asset.id for asset in safe_assets]),
    ]
    for label, model, ids in delete_sets:
        if not ids:
            summary.deleted[label] = 0
            continue
        result = await db.execute(delete(model).where(model.id.in_(ids)))
        summary.deleted[label] = max(0, int(result.rowcount or 0))

    await db.commit()
    _remove_local_paths(
        settings,
        job_ids=[str(row.job_id) for row in job_rows],
        execution_rows=auto_execution_rows,
        summary=summary,
    )
    logger.warning(
        "Generated-data retention cleanup completed: deleted=%s cutoff=%s keep_latest=%s",
        summary.deleted,
        summary.cutoff.isoformat(),
        summary.keep_latest,
    )
    return summary
