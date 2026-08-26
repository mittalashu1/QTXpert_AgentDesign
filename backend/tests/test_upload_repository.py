from app.services.upload_repository import UploadRepositoryService


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
