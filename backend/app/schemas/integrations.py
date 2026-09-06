"""API contracts for the organization integrations settings skeleton."""
import re
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


IntegrationProvider = Literal[
    "jira",
    "confluence",
    "github",
    "gitlab",
    "azure_devops",
    "test_case_repository",
    "rest_api",
    "database",
    "object_storage",
    "slack",
]
IntegrationScope = Literal["organization", "project"]
IntegrationStatus = Literal[
    "not_configured",
    "configured",
    "ready_for_test",
    "needs_reauth",
    "error",
    "disabled",
]
NotificationMode = Literal["all", "important", "none"]

_SECRET_REF_RE = re.compile(
    r"^(vault|env|secret|aws-secretsmanager|azure-keyvault|gcp-secret)://[A-Za-z0-9._/@:-]{1,500}$"
)
_SENSITIVE_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "authorization",
    "credential",
)


def _validate_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain embedded credentials")
    return value.strip()


def _validate_secret_ref(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    candidate = value.strip()
    lowered = candidate.lower()
    if any(marker in lowered for marker in ("password=", "token=", "secret=", "bearer ", "api_key=")):
        raise ValueError("Store a secret-manager reference, not a credential value")
    if not _SECRET_REF_RE.fullmatch(candidate):
        raise ValueError(
            "secret_ref must be an opaque vault://, env://, secret://, or cloud secret reference"
        )
    return candidate


def _validate_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if len(value) > 24:
        raise ValueError("metadata may contain at most 24 keys")

    def walk(current: Any, path: str = "") -> None:
        if isinstance(current, dict):
            for key, child in current.items():
                key_text = str(key)
                lowered = key_text.lower()
                if any(marker in lowered for marker in _SENSITIVE_MARKERS):
                    raise ValueError("metadata cannot contain secret or credential fields")
                walk(child, f"{path}.{key_text}")
        elif isinstance(current, list):
            if len(current) > 32:
                raise ValueError("metadata lists may contain at most 32 values")
            for index, child in enumerate(current):
                walk(child, f"{path}[{index}]")
        elif isinstance(current, str):
            lowered = current.lower()
            if any(marker in lowered for marker in ("password=", "token=", "secret=", "bearer ", "api_key=")):
                raise ValueError("metadata cannot contain credential values")
            if len(current) > 1000:
                raise ValueError("metadata text values are limited to 1000 characters")
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            raise ValueError("metadata must contain JSON-safe scalar, list, or object values")

    walk(value)
    return value


class IntegrationCatalogItem(BaseModel):
    key: IntegrationProvider
    label: str
    category: str
    description: str
    capabilities: list[str]
    auth_methods: list[str]
    recommended_scope: IntegrationScope
    docs_url: str | None = None


class IntegrationConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: IntegrationProvider
    name: str = Field(min_length=1, max_length=160)
    scope: IntegrationScope = "organization"
    project_id: UUID | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    external_org: str | None = Field(default=None, max_length=255)
    external_project: str | None = Field(default=None, max_length=255)
    secret_ref: str | None = Field(default=None, max_length=512)
    scopes: list[str] = Field(default_factory=list, max_length=32)
    metadata: dict[str, Any] | None = None
    enabled: bool = False

    _url = field_validator("base_url")( _validate_url)
    _secret = field_validator("secret_ref")( _validate_secret_ref)
    _metadata = field_validator("metadata")( _validate_metadata)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str]) -> list[str]:
        clean = [value.strip() for value in values if value.strip()]
        if any(len(value) > 120 for value in clean):
            raise ValueError("each permission scope is limited to 120 characters")
        if any(any(marker in value.lower() for marker in _SENSITIVE_MARKERS) for value in clean):
            raise ValueError("scopes cannot contain credential values")
        return clean

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "project" and self.project_id is None:
            raise ValueError("project_id is required for a project-scoped connection")
        if self.scope == "organization" and self.project_id is not None:
            raise ValueError("organization-scoped connections cannot include project_id")
        return self


class IntegrationConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    project_id: UUID | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    external_org: str | None = Field(default=None, max_length=255)
    external_project: str | None = Field(default=None, max_length=255)
    secret_ref: str | None = Field(default=None, max_length=512)
    scopes: list[str] | None = Field(default=None, max_length=32)
    metadata: dict[str, Any] | None = None
    enabled: bool | None = None

    _url = field_validator("base_url")( _validate_url)
    _secret = field_validator("secret_ref")( _validate_secret_ref)
    _metadata = field_validator("metadata")( _validate_metadata)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        clean = [value.strip() for value in values if value.strip()]
        if any(len(value) > 120 for value in clean):
            raise ValueError("each permission scope is limited to 120 characters")
        if any(any(marker in value.lower() for marker in _SENSITIVE_MARKERS) for value in clean):
            raise ValueError("scopes cannot contain credential values")
        return clean


class IntegrationConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None
    provider: IntegrationProvider
    name: str
    scope: IntegrationScope
    status: IntegrationStatus
    enabled: bool
    base_url: str | None
    external_org: str | None
    external_project: str | None
    scopes: list[str]
    metadata: dict[str, Any]
    secret_configured: bool
    last_tested_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class IntegrationConnectionTestOut(BaseModel):
    id: UUID
    provider: IntegrationProvider
    status: IntegrationStatus
    healthy: bool
    external_call_made: bool = False
    checked_at: datetime
    message: str


class IntegrationUserPreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_provider: IntegrationProvider | None = None
    default_connection_id: UUID | None = None
    notifications_enabled: bool = True
    notification_mode: NotificationMode = "important"
    timezone: str = Field(default="Asia/Dubai", min_length=1, max_length=80)


class IntegrationUserPreferencesOut(IntegrationUserPreferencesIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class IntegrationOverviewOut(BaseModel):
    workspace_label: str
    role: str
    can_manage_connections: bool
    connection_count: int
    configured_connection_count: int
    catalog: list[IntegrationCatalogItem]
    preferences: IntegrationUserPreferencesOut | None
