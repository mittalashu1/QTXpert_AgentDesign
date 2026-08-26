from app.schemas.requirement import ProjectUpdate
from app.schemas.test_case import GenerationRunTitleUpdate


def test_project_update_trims_at_route_but_requires_non_empty_schema_value():
    update = ProjectUpdate(name="Renamed project", description="Updated")
    assert update.name == "Renamed project"


def test_generation_run_title_update_accepts_user_label():
    update = GenerationRunTitleUpdate(title="Regression - Payments")
    assert update.title == "Regression - Payments"
