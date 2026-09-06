"""Add the organization integration settings skeleton.

Only connector metadata and opaque secret-manager references are persisted;
the migration deliberately has no credential columns or remote side effects.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0026_integration_settings"
down_revision: Union[str, Sequence[str], None] = "0025_unified_defect_logging"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="organization"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="not_configured"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("base_url", sa.String(length=2048), nullable=True),
        sa.Column("external_org", sa.String(length=255), nullable=True),
        sa.Column("external_project", sa.String(length=255), nullable=True),
        sa.Column("secret_ref", sa.String(length=512), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_integration_connections_owner_id", "integration_connections", ["owner_id"])
    op.create_index("ix_integration_connections_project_id", "integration_connections", ["project_id"])
    op.create_index("ix_integration_connections_provider", "integration_connections", ["provider"])
    op.create_index(
        "ix_integration_connections_owner_project_provider",
        "integration_connections",
        ["owner_id", "project_id", "provider"],
    )

    op.create_table(
        "integration_user_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("default_provider", sa.String(length=40), nullable=True),
        sa.Column("default_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notification_mode", sa.String(length=20), nullable=False, server_default="important"),
        sa.Column("timezone", sa.String(length=80), nullable=False, server_default="Asia/Dubai"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["default_connection_id"], ["integration_connections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_integration_user_preferences_user_id"),
    )


def downgrade() -> None:
    op.drop_table("integration_user_preferences")
    op.drop_index("ix_integration_connections_owner_project_provider", table_name="integration_connections")
    op.drop_index("ix_integration_connections_provider", table_name="integration_connections")
    op.drop_index("ix_integration_connections_project_id", table_name="integration_connections")
    op.drop_index("ix_integration_connections_owner_id", table_name="integration_connections")
    op.drop_table("integration_connections")
