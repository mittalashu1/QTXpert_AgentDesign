import asyncio
from types import SimpleNamespace

import pytest

from app.services.upload_repository import UploadRepositoryService
from app.config import Settings
from app.database.models.uploaded_asset import UploadedAsset
from uuid import uuid4


def test_upload_repository_classifies_android_builds():
    assert UploadRepositoryService.category_for_filename("Retail-UAT.apk") == "apk"


def test_upload_repository_classifies_design_documents():
    assert UploadRepositoryService.category_for_filename("BRD-v4.pdf") == "document"
    assert UploadRepositoryService.category_for_filename("jira-export.json") == "document"
    assert UploadRepositoryService.category_for_filename("stories.csv") == "document"
    assert UploadRepositoryService.category_for_filename("release-deck.pptx") == "document"
    assert UploadRepositoryService.category_for_filename("requirements.html") == "document"


def test_upload_repository_classifies_test_data():
    assert UploadRepositoryService.category_for_filename("customers.xlsx") == "test_data"
    assert UploadRepositoryService.category_for_filename("environment.yaml") == "test_data"


def test_upload_repository_keeps_unknown_files_separate():
    assert UploadRepositoryService.category_for_filename("binary.dat") == "other"


def test_upload_repository_recovers_legacy_document_categories():
    legacy_spreadsheet = UploadedAsset(
        extension="xlsx",
        category="test_data",
        source_module="repository_documents",
        status="ready",
    )
    assert UploadRepositoryService.is_reusable_document(legacy_spreadsheet)


def test_upload_repository_keeps_test_data_and_builds_out_of_document_context():
    test_data = UploadedAsset(extension="xlsx", category="test_data", source_module="test_data", status="ready")
    build = UploadedAsset(extension="apk", category="apk", source_module="repository_documents", status="ready")
    assert not UploadRepositoryService.is_reusable_document(test_data)
    assert not UploadRepositoryService.is_reusable_document(build)


def test_object_storage_key_is_project_scoped_and_path_safe():
    settings = Settings(
        UPLOAD_STORAGE_BACKEND="object_store",
        OBJECT_STORAGE_BUCKET="qtxpert-artifacts",
        OBJECT_STORAGE_ACCESS_KEY_ID="access",
        OBJECT_STORAGE_SECRET_ACCESS_KEY="secret",
        OBJECT_STORAGE_PREFIX="qtxpert-prod",
    )
    asset = UploadedAsset(
        id=uuid4(),
        owner_id=uuid4(),
        project_id=uuid4(),
        filename="../investnation.apk",
        extension="apk",
        category="apk",
        source_module="autopilot",
    )
    key = UploadRepositoryService._object_key(settings, asset)
    assert key.startswith("qtxpert-prod/projects/")
    assert "../" not in key
    assert key.endswith("/investnation.apk")


def test_object_storage_requires_all_credentials():
    settings = Settings(UPLOAD_STORAGE_BACKEND="object_store", OBJECT_STORAGE_BUCKET="bucket")
    assert settings.object_storage_configured is False


@pytest.mark.asyncio
async def test_concurrent_materialization_uses_isolated_staging_files(tmp_path, monkeypatch):
    """A resume request and a status retry may materialize the same APK together."""
    asset_id = uuid4()
    owner_id = uuid4()
    asset = SimpleNamespace(
        id=asset_id,
        storage_backend="postgres_chunks",
    )

    async def get_owned(cls, _db, requested_asset_id, requested_owner_id):
        assert requested_asset_id == asset_id
        assert requested_owner_id == owner_id
        return asset

    async def iter_content(cls, _db, _asset_id, *, settings=None):
        # Yield control while both writers have their own staging file open.
        await asyncio.sleep(0.01)
        yield b"investnation-apk"

    monkeypatch.setattr(UploadRepositoryService, "get_owned", classmethod(get_owned))
    monkeypatch.setattr(UploadRepositoryService, "iter_content", classmethod(iter_content))

    target = tmp_path / "job" / "investnation.apk"
    results = await asyncio.gather(
        UploadRepositoryService.materialize(None, asset_id, owner_id, target),
        UploadRepositoryService.materialize(None, asset_id, owner_id, target),
    )

    assert results == [asset, asset]
    assert target.read_bytes() == b"investnation-apk"
    assert list(target.parent.glob("*.part")) == []
