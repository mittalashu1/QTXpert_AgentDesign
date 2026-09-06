"""Organization and project integration settings.

The connector registry intentionally stores metadata only.  OAuth tokens,
PATs, database passwords, and webhook secrets belong in a secret manager and
are represented here by an opaque ``secret_ref`` such as ``vault://...``.
"""
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.database.session import Base

if TYPE_CHECKING:
    from app.database.models.project import Project
    from app.database.models.user import User


class IntegrationConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A workspace-owned integration definition.

    ``owner_id`` is the current workspace boundary in this release.  A future
    organization/membership table can replace it without changing connector
    payloads.  ``project_id`` narrows a connection to one owned project when
    ``scope`` is ``project``.
    """

    __tablename__ = "integration_connections"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="organization", server_default="organization")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="not_configured", server_default="not_configured")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    base_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    external_org: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_project: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Only an opaque pointer is persisted.  The referenced secret is resolved
    # by a future connector adapter at execution time.
    secret_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    scopes: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    last_tested_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id])
    project: Mapped[Optional["Project"]] = relationship(foreign_keys=[project_id])


class IntegrationUserPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Personal defaults and notifications for the integrations workspace."""

    __tablename__ = "integration_user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    default_provider: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    default_connection_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("integration_connections.id", ondelete="SET NULL"), nullable=True
    )
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    notification_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="important", server_default="important")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="Asia/Dubai", server_default="Asia/Dubai")

    user: Mapped["User"] = relationship(foreign_keys=[user_id])
    default_connection: Mapped[Optional[IntegrationConnection]] = relationship(
        foreign_keys=[default_connection_id]
    )
