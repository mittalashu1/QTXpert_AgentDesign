"""Contract tests for evidence-aware, local-first defect logging."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.routes.autopilot import (
    _autopilot_execution_snapshot,
    _suite_defect_evidence,
)
from app.api.routes.executions import _execution_evidence_assets
from app.schemas.execution import AutopilotDefectCreate


def test_execution_evidence_assets_keeps_opaque_ids_and_drops_paths():
    screenshot_id = uuid4()
    video_id = uuid4()
    page_source_id = uuid4()
    evidence = {
        "screenshot_asset_id": str(screenshot_id),
        "screenshot_asset_id_filename": "failure.png",
        "video_path": "C:/worker/secrets/functional-journey.mp4",
        "page_source_asset_id": str(page_source_id),
        "evidence_assets": [
            {"asset_id": str(video_id), "kind": "video", "filename": "journey.mp4"},
            {"asset_id": "not-a-uuid", "kind": "video", "filename": "bad.mp4"},
            {"asset_id": str(screenshot_id), "kind": "screenshot", "filename": "duplicate.png"},
        ],
    }

    assets = _execution_evidence_assets(evidence)

    assert [item["asset_id"] for item in assets] == [
        str(screenshot_id),
        str(page_source_id),
        str(video_id),
    ]
    assert all("path" not in item for item in assets)


def test_suite_defect_evidence_deduplicates_and_caps_assets():
    asset_ids = [uuid4() for _ in range(22)]
    test = {
        "evidence": {
            "evidence_dir": "C:/worker/should-never-be-persisted",
            "evidence_assets": [
                *({"asset_id": str(asset_id), "kind": "video", "filename": f"{index}.mp4"} for index, asset_id in enumerate(asset_ids)),
                {"asset_id": str(asset_ids[0]), "kind": "video", "filename": "duplicate.mp4"},
            ],
        }
    }

    assets = _suite_defect_evidence(test)

    assert len(assets) == 20
    assert [item["asset_id"] for item in assets] == [str(item) for item in asset_ids[:20]]
    assert all("evidence_dir" not in item for item in assets)


def test_autopilot_snapshot_is_bounded_and_secret_safe():
    execution_id = uuid4()
    suite = {
        "status": "failed",
        "target_kind": "android",
        "target_url": "https://qa.example.test/login?token=do-not-store#secret",
        "provider": "browserstack",
    }
    test = {
        "test_id": "QT-FUNC-001",
        "title": "Sign in",
        "status": "failed",
        "error": "password=super-secret",
    }
    smoke = [
        SimpleNamespace(
            id=execution_id,
            status="failed",
            provider="browserstack",
            device_name="Pixel",
            platform_version="14",
            started_at=None,
            finished_at=None,
            duration_seconds=2.0,
            error="token=do-not-store",
            screenshot_asset_id=None,
            page_source_asset_id=None,
        )
    ]

    snapshot = _autopilot_execution_snapshot(suite, test, smoke)

    assert snapshot["target_url"] == "https://qa.example.test/login"
    assert snapshot["error"] == "password: [REDACTED]"
    assert snapshot["smoke_history"][0]["error"] == "token: [REDACTED]"
    assert "do-not-store" not in str(snapshot)
    assert "path" not in str(snapshot).lower()


def test_autopilot_defect_payload_defaults_to_local_major_draft():
    payload = AutopilotDefectCreate(test_id="QT-FUNC-001")

    assert payload.severity == "major"
    assert payload.integration_provider == "local"
