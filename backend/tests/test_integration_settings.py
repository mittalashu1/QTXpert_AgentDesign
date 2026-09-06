"""Contract tests for the secret-safe integration settings boundary."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.routes.settings import INTEGRATION_CATALOG, _connection_out
from app.database.models.integration import IntegrationConnection
from app.schemas.integrations import IntegrationConnectionCreate, IntegrationConnectionPatch


def test_catalog_covers_core_enterprise_boundaries():
    keys = {item.key for item in INTEGRATION_CATALOG}
    assert {"jira", "confluence", "github", "test_case_repository", "database"}.issubset(keys)
    assert all(item.capabilities and item.auth_methods for item in INTEGRATION_CATALOG)


def test_organization_connection_cannot_claim_a_project():
    with pytest.raises(ValidationError):
        IntegrationConnectionCreate(
            provider="jira",
            name="Jira",
            scope="organization",
            project_id=uuid4(),
        )


def test_project_connection_requires_a_project():
    with pytest.raises(ValidationError):
        IntegrationConnectionCreate(provider="database", name="Read model", scope="project")


@pytest.mark.parametrize("secret_ref", ["plain-token", "token=abc", "Bearer abc", "api_key=abc"])
def test_raw_credentials_are_rejected(secret_ref: str):
    with pytest.raises(ValidationError):
        IntegrationConnectionCreate(provider="jira", name="Jira", secret_ref=secret_ref)


@pytest.mark.parametrize("secret_ref", ["vault://qtxpert/jira/prod", "env://JIRA_TOKEN", "aws-secretsmanager://qtxpert/jira"])
def test_opaque_secret_references_are_allowed(secret_ref: str):
    connection = IntegrationConnectionCreate(provider="jira", name="Jira", secret_ref=secret_ref)
    assert connection.secret_ref == secret_ref


def test_metadata_rejects_sensitive_keys():
    with pytest.raises(ValidationError):
        IntegrationConnectionCreate(
            provider="database",
            name="Read model",
            scope="project",
            project_id=uuid4(),
            metadata={"password": "do-not-store"},
        )


def test_patch_allows_rotation_by_reference_only():
    patch = IntegrationConnectionPatch(secret_ref="env://JIRA_TOKEN", enabled=True)
    assert patch.secret_ref == "env://JIRA_TOKEN"


def test_connection_response_redacts_secret_reference():
    now = datetime.now(timezone.utc)
    connection = IntegrationConnection(
        id=uuid4(),
        owner_id=uuid4(),
        provider="jira",
        name="Jira",
        scope="organization",
        status="ready_for_test",
        enabled=True,
        secret_ref="vault://qtxpert/jira/prod",
        scopes=["read:requirements"],
        metadata_json={"workspace": "quality"},
        created_at=now,
        updated_at=now,
    )
    response = _connection_out(connection)
    serialized = response.model_dump()
    assert response.secret_configured is True
    assert "secret_ref" not in serialized
    assert "vault://qtxpert/jira/prod" not in str(serialized)
