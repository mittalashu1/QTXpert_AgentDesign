from datetime import datetime, timezone
from typing import Annotated, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth_deps import get_current_user, require_roles
from app.database.models.config_and_audit import ApiConfiguration, AuditLog
from app.database.models.integration import IntegrationConnection, IntegrationUserPreference
from app.database.models.project import Project
from app.database.models.user import User, UserRole
from app.database.session import get_db_session
from app.llm.base import LLMMessage, LLMProviderError
from app.llm.factory import get_llm_provider
from app.schemas.integrations import (
    IntegrationCatalogItem,
    IntegrationConnectionCreate,
    IntegrationConnectionOut,
    IntegrationConnectionPatch,
    IntegrationConnectionTestOut,
    IntegrationOverviewOut,
    IntegrationStatus,
    IntegrationUserPreferencesIn,
    IntegrationUserPreferencesOut,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class ApiConfigurationIn(BaseModel):
    name: str
    llm_provider: str
    llm_model: str
    is_active: bool = True


class ApiConfigurationOut(ApiConfigurationIn):
    model_config = ConfigDict(from_attributes=True)

    id: str


class ProviderTestRequest(BaseModel):
    provider: str


class ProviderTestResult(BaseModel):
    provider: str
    healthy: bool
    detail: str = ""


# This catalog is deliberately declarative.  It describes the integration
# boundary in the UI without pretending a remote connector is configured.
# Provider adapters can be added one at a time behind this stable contract.
INTEGRATION_CATALOG: tuple[IntegrationCatalogItem, ...] = (
    IntegrationCatalogItem(
        key="jira",
        label="Jira",
        category="Work tracking",
        description="Import requirements and prepare evidence-linked defect drafts.",
        capabilities=["requirements", "defects", "status sync"],
        auth_methods=["Atlassian OAuth 2.0", "least-privilege API token"],
        recommended_scope="organization",
        docs_url="https://developer.atlassian.com/cloud/jira/platform/rest/v3/",
    ),
    IntegrationCatalogItem(
        key="confluence",
        label="Confluence",
        category="Knowledge",
        description="Bring approved product, architecture, and test-plan pages into Document Intelligence.",
        capabilities=["page import", "space selection", "traceability"],
        auth_methods=["Atlassian OAuth 2.0"],
        recommended_scope="organization",
        docs_url="https://developer.atlassian.com/cloud/confluence/rest/v2/",
    ),
    IntegrationCatalogItem(
        key="github",
        label="GitHub",
        category="Source control",
        description="Link repositories and pull requests to requirements, changes, and test evidence.",
        capabilities=["repository context", "pull requests", "webhooks"],
        auth_methods=["GitHub App", "fine-grained PAT"],
        recommended_scope="organization",
        docs_url="https://docs.github.com/en/apps/creating-github-apps",
    ),
    IntegrationCatalogItem(
        key="gitlab",
        label="GitLab",
        category="Source control",
        description="Connect groups and projects for change-aware test coverage.",
        capabilities=["project context", "merge requests", "webhooks"],
        auth_methods=["OAuth 2.0", "scoped access token"],
        recommended_scope="organization",
        docs_url="https://docs.gitlab.com/ee/api/",
    ),
    IntegrationCatalogItem(
        key="azure_devops",
        label="Azure DevOps",
        category="Source and work tracking",
        description="Map work items, repos, and pipelines to QTXpert evidence.",
        capabilities=["work items", "repositories", "pipelines"],
        auth_methods=["Microsoft OAuth", "scoped PAT"],
        recommended_scope="organization",
        docs_url="https://learn.microsoft.com/en-us/rest/api/azure/devops/",
    ),
    IntegrationCatalogItem(
        key="test_case_repository",
        label="Test case repository",
        category="Quality systems",
        description="Import and publish versioned test cases from a customer-owned QA repository.",
        capabilities=["case import", "version mapping", "result export"],
        auth_methods=["OAuth 2.0", "scoped API token"],
        recommended_scope="project",
    ),
    IntegrationCatalogItem(
        key="rest_api",
        label="REST / GraphQL API",
        category="Application data",
        description="Define an approved read-only endpoint for contract and oracle checks.",
        capabilities=["OpenAPI context", "contract checks", "test-data lookup"],
        auth_methods=["OAuth 2.0", "mTLS", "secret-manager reference"],
        recommended_scope="project",
    ),
    IntegrationCatalogItem(
        key="database",
        label="Database (read-only)",
        category="Application data",
        description="Attach a read-only non-production database for data integrity and oracle validation.",
        capabilities=["schema discovery", "read-only queries", "data assertions"],
        auth_methods=["mTLS", "secret-manager reference"],
        recommended_scope="project",
    ),
    IntegrationCatalogItem(
        key="object_storage",
        label="Object storage",
        category="Evidence and artifacts",
        description="Store large evidence and test artifacts in a private customer bucket.",
        capabilities=["evidence upload", "signed downloads", "retention"],
        auth_methods=["workload identity", "scoped access key"],
        recommended_scope="organization",
        docs_url="https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html",
    ),
    IntegrationCatalogItem(
        key="slack",
        label="Slack",
        category="Notifications",
        description="Send important run, defect, and approval notifications to a controlled channel.",
        capabilities=["run alerts", "defect alerts", "approvals"],
        auth_methods=["OAuth 2.0", "scoped app token"],
        recommended_scope="organization",
        docs_url="https://api.slack.com/authentication",
    ),
)

_INTEGRATION_STATUSES = {
    "not_configured",
    "configured",
    "ready_for_test",
    "needs_reauth",
    "error",
    "disabled",
}


def _connection_out(connection: IntegrationConnection) -> IntegrationConnectionOut:
    """Serialize a connection without ever returning its secret reference."""
    raw_status = connection.status if connection.status in _INTEGRATION_STATUSES else "error"
    return IntegrationConnectionOut(
        id=connection.id,
        project_id=connection.project_id,
        provider=connection.provider,
        name=connection.name,
        scope=connection.scope,
        status=raw_status,
        enabled=connection.enabled,
        base_url=connection.base_url,
        external_org=connection.external_org,
        external_project=connection.external_project,
        scopes=list(connection.scopes or []),
        metadata=dict(connection.metadata_json or {}),
        secret_configured=bool(connection.secret_ref),
        last_tested_at=connection.last_tested_at,
        last_error=connection.last_error,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _audit(db: AsyncSession, actor: User, action: str, resource_id: str | None, detail: dict | None = None) -> None:
    """Record connector lifecycle events with metadata only."""
    db.add(
        AuditLog(
            user_id=actor.id,
            action=action,
            resource_type="integration_connection",
            resource_id=resource_id,
            detail=detail,
        )
    )


async def _owned_project_or_404(db: AsyncSession, project_id: UUID | None, user: User) -> None:
    if project_id is None:
        return
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.owner_id == user.id)
    )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


async def _owned_connection_or_404(db: AsyncSession, connection_id: UUID, user: User) -> IntegrationConnection:
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.owner_id == user.id,
        )
    )
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration connection not found")
    return connection


async def _preferences_for_user(db: AsyncSession, user: User) -> IntegrationUserPreference | None:
    return await db.scalar(
        select(IntegrationUserPreference).where(IntegrationUserPreference.user_id == user.id)
    )


@router.get("", response_model=List[ApiConfigurationOut])
async def list_configurations(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    result = await db.execute(select(ApiConfiguration))
    rows = result.scalars().all()
    return [
        ApiConfigurationOut(
            id=str(row.id),
            name=row.name,
            llm_provider=row.llm_provider,
            llm_model=row.llm_model,
            is_active=row.is_active,
        )
        for row in rows
    ]


@router.post("", response_model=ApiConfigurationOut, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    payload: ApiConfigurationIn,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
):
    config = ApiConfiguration(**payload.model_dump())
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return ApiConfigurationOut(
        id=str(config.id),
        name=config.name,
        llm_provider=config.llm_provider,
        llm_model=config.llm_model,
        is_active=config.is_active,
    )


@router.post("/test-provider", response_model=ProviderTestResult)
async def test_provider(
    payload: ProviderTestRequest,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    try:
        provider = get_llm_provider(payload.provider)
        # Call complete() directly (not health_check()) so any Azure/OpenAI
        # error message actually propagates back to the UI instead of being
        # swallowed into a bare True/False by health_check()'s broad except.
        await provider.complete(
            [LLMMessage(role="user", content="ping")],
            max_tokens=5,
        )
        return ProviderTestResult(provider=payload.provider, healthy=True)
    except LLMProviderError as exc:
        return ProviderTestResult(provider=payload.provider, healthy=False, detail=str(exc))


@router.get("/integrations/catalog", response_model=List[IntegrationCatalogItem])
async def list_integration_catalog(
    user: Annotated[User, Depends(get_current_user)],
):
    """Return the supported connector catalogue without exposing credentials."""
    return list(INTEGRATION_CATALOG)


@router.get("/integrations", response_model=List[IntegrationConnectionOut])
async def list_integrations(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
    project_id: UUID | None = None,
):
    """List this manager's organization/project connector definitions.

    The current product has no organization table yet, so ``owner_id`` is the
    explicit workspace boundary.  It prevents a connector configured by one
    customer account from being returned to another account.
    """
    query = select(IntegrationConnection).where(IntegrationConnection.owner_id == user.id)
    if project_id is not None:
        await _owned_project_or_404(db, project_id, user)
        query = query.where(IntegrationConnection.project_id == project_id)
    result = await db.execute(query.order_by(IntegrationConnection.updated_at.desc()))
    return [_connection_out(row) for row in result.scalars().all()]


@router.post("/integrations", response_model=IntegrationConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_integration(
    payload: IntegrationConnectionCreate,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    await _owned_project_or_404(db, payload.project_id, user)
    connection_status = "ready_for_test" if payload.secret_ref else "not_configured"
    if not payload.enabled and payload.secret_ref:
        connection_status = "disabled"
    connection = IntegrationConnection(
        owner_id=user.id,
        project_id=payload.project_id,
        provider=payload.provider,
        name=payload.name.strip(),
        scope=payload.scope,
        status=connection_status,
        enabled=payload.enabled,
        base_url=payload.base_url,
        external_org=payload.external_org,
        external_project=payload.external_project,
        secret_ref=payload.secret_ref,
        scopes=payload.scopes,
        metadata_json=payload.metadata,
    )
    db.add(connection)
    await db.flush()
    _audit(
        db,
        user,
        "integration_connection_created",
        str(connection.id),
        {"provider": connection.provider, "scope": connection.scope, "project_id": str(connection.project_id) if connection.project_id else None},
    )
    await db.commit()
    await db.refresh(connection)
    return _connection_out(connection)


@router.patch("/integrations/{connection_id}", response_model=IntegrationConnectionOut)
async def update_integration(
    connection_id: UUID,
    payload: IntegrationConnectionPatch,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    connection = await _owned_connection_or_404(db, connection_id, user)
    changes = payload.model_dump(exclude_unset=True)
    if "project_id" in changes:
        if connection.scope == "project" and changes["project_id"] is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="project_id is required for a project-scoped connection")
        await _owned_project_or_404(db, changes["project_id"], user)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    if "metadata" in changes:
        changes["metadata_json"] = changes.pop("metadata")
    for key, value in changes.items():
        setattr(connection, key, value)
    # Any credential or endpoint change requires a fresh validation cycle.
    if any(key in changes for key in {"base_url", "external_org", "external_project", "secret_ref", "scopes", "metadata_json", "project_id"}):
        connection.last_tested_at = None
        connection.last_error = None
    if "enabled" in changes or "secret_ref" in changes:
        if not connection.enabled and connection.secret_ref:
            connection.status = "disabled"
        elif connection.secret_ref:
            connection.status = "ready_for_test"
        else:
            connection.status = "not_configured"
    _audit(
        db,
        user,
        "integration_connection_updated",
        str(connection.id),
        {"provider": connection.provider, "scope": connection.scope, "project_id": str(connection.project_id) if connection.project_id else None, "fields": sorted(changes)},
    )
    await db.commit()
    await db.refresh(connection)
    return _connection_out(connection)


@router.delete("/integrations/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    connection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    connection = await _owned_connection_or_404(db, connection_id, user)
    resource_id = str(connection.id)
    _audit(
        db,
        user,
        "integration_connection_deleted",
        resource_id,
        {"provider": connection.provider, "scope": connection.scope},
    )
    await db.delete(connection)
    await db.commit()
    return None


@router.post("/integrations/{connection_id}/test", response_model=IntegrationConnectionTestOut)
async def test_integration(
    connection_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.QA_LEAD))],
):
    """Validate the local configuration without making a remote request.

    The connector adapters will perform a bounded, provider-specific health
    check once OAuth/PAT/database secret resolution is wired.  Returning this
    explicit state prevents a settings click from being mistaken for a live
    Jira/Confluence/database connection.
    """
    connection = await _owned_connection_or_404(db, connection_id, user)
    checked_at = datetime.now(timezone.utc)
    if not connection.enabled:
        result_status: IntegrationStatus = "disabled"
        message = "Connection is disabled. Enable it after completing the secret-manager reference."
    elif not connection.secret_ref:
        result_status = "needs_reauth"
        message = "Metadata is saved, but a secret-manager reference is still required; no external request was made."
    else:
        result_status = "ready_for_test"
        message = "Metadata and secret reference validated. The provider adapter is not enabled in this skeleton; no external request was made."
    connection.status = result_status
    connection.last_tested_at = checked_at
    connection.last_error = None
    _audit(
        db,
        user,
        "integration_connection_tested",
        str(connection.id),
        {"provider": connection.provider, "status": result_status, "external_call_made": False},
    )
    await db.commit()
    return IntegrationConnectionTestOut(
        id=connection.id,
        provider=connection.provider,
        status=result_status,
        healthy=False,
        external_call_made=False,
        checked_at=checked_at,
        message=message,
    )


@router.get("/me/integration-preferences", response_model=IntegrationUserPreferencesOut | None)
async def get_integration_preferences(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    return await _preferences_for_user(db, user)


@router.put("/me/integration-preferences", response_model=IntegrationUserPreferencesOut)
async def update_integration_preferences(
    payload: IntegrationUserPreferencesIn,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    if payload.default_connection_id is not None:
        connection = await db.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.id == payload.default_connection_id,
                IntegrationConnection.owner_id == user.id,
            )
        )
        if connection is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Default integration connection not found")
        if payload.default_provider and payload.default_provider != connection.provider:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="default_provider must match the selected connection")

    preference = await _preferences_for_user(db, user)
    if preference is None:
        preference = IntegrationUserPreference(user_id=user.id)
        db.add(preference)
    for key, value in payload.model_dump().items():
        setattr(preference, key, value)
    await db.commit()
    await db.refresh(preference)
    return IntegrationUserPreferencesOut.model_validate(preference)


@router.get("/overview", response_model=IntegrationOverviewOut)
async def integration_overview(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    can_manage = user.role in {UserRole.ADMIN, UserRole.QA_LEAD}
    connections: list[IntegrationConnection] = []
    if can_manage:
        result = await db.execute(
            select(IntegrationConnection).where(IntegrationConnection.owner_id == user.id)
        )
        connections = list(result.scalars().all())
    configured_count = sum(1 for row in connections if row.status in {"configured", "ready_for_test"})
    preference = await _preferences_for_user(db, user)
    preference_out = IntegrationUserPreferencesOut.model_validate(preference) if preference else None
    workspace_label = f"{user.full_name.strip() or 'Your'} workspace"
    return IntegrationOverviewOut(
        workspace_label=workspace_label,
        role=user.role.value,
        can_manage_connections=can_manage,
        connection_count=len(connections),
        configured_connection_count=configured_count,
        catalog=list(INTEGRATION_CATALOG),
        preferences=preference_out,
    )
