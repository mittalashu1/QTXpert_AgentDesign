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


def test_upload_repository_classifies_test_data():
    assert UploadRepositoryService.category_for_filename("customers.xlsx") == "test_data"
    assert UploadRepositoryService.category_for_filename("environment.yaml") == "test_data"


def test_upload_repository_keeps_unknown_files_separate():
    assert UploadRepositoryService.category_for_filename("binary.dat") == "other"


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
