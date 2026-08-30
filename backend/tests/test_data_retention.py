from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import Settings
from app.services.data_retention import (
    RetentionSummary,
    _ids_from_json,
    _normalise_datetime,
    _safe_job_path,
)


def test_retention_defaults_are_conservative():
    settings = Settings(
        POSTGRES_URL="postgresql+asyncpg://qtxpert:qtxpert@localhost:5432/qtxpert_test",
        JWT_SECRET="test-secret",
    )
    assert settings.DATA_RETENTION_ENABLED is False
    assert settings.DATA_RETENTION_DAYS == 7
    assert settings.DATA_RETENTION_KEEP_LATEST == 3
    assert settings.DATA_RETENTION_INCLUDE_EPHEMERAL_ASSETS is True
    assert settings.DATA_RETENTION_RUN_ON_STARTUP is False


def test_retention_summary_serializes_counts_and_cutoff():
    cutoff = datetime(2026, 8, 23, tzinfo=timezone.utc)
    summary = RetentionSummary(
        cutoff=cutoff,
        keep_latest=3,
        dry_run=True,
        candidates={"generation_runs": 4},
        protected={"generation_runs_with_execution_results": 1},
    )
    value = summary.as_dict()
    assert value["cutoff"] == cutoff.isoformat()
    assert value["candidate_total"] == 4
    assert value["deleted_total"] == 0
    assert value["dry_run"] is True


def test_retention_extracts_only_asset_like_ids_from_metadata():
    asset_id = UUID("11111111-1111-1111-1111-111111111111")
    value = _ids_from_json(
        {
            "screenshot_asset_id": str(asset_id),
            "asset_ids": [str(asset_id)],
            "nested": [{"page_source_asset_id": str(asset_id)}],
            "unrelated": str(asset_id),
        }
    )
    assert value == {asset_id}


def test_retention_normalizes_naive_datetimes_to_utc():
    value = _normalise_datetime(datetime(2026, 8, 30, 12, 0, 0))
    assert value.tzinfo == timezone.utc


def test_retention_job_paths_cannot_escape_storage_root(tmp_path: Path):
    valid = _safe_job_path(tmp_path, "11111111-1111-1111-1111-111111111111")
    assert valid == tmp_path / "11111111-1111-1111-1111-111111111111"
    assert _safe_job_path(tmp_path, "../../etc") is None
    assert _safe_job_path(tmp_path, "not-a-uuid") is None
