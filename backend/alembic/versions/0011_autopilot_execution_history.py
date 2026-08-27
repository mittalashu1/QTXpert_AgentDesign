"""Persist Autopilot safe-smoke execution history and evidence references.

Revision ID: 0011_autopilot_execution_history
Revises: 0010_document_intelligence
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_autopilot_execution_history"
down_revision: Union[str, Sequence[str], None] = "0010_document_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autopilot_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "autopilot_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("autopilot_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=False),
        sa.Column("platform_version", sa.String(length=50), nullable=True),
        sa.Column("appium_url", sa.String(length=2048), nullable=True),
        sa.Column("appium_app", sa.String(length=2048), nullable=True),
        sa.Column("no_reset", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("auto_grant_permissions", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("current_package", sa.String(length=255), nullable=True),
        sa.Column("current_activity", sa.String(length=500), nullable=True),
        sa.Column(
            "screenshot_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "page_source_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_autopilot_executions_job_created",
        "autopilot_executions",
        ["autopilot_job_id", "created_at"],
    )
    op.create_index(
        "ix_autopilot_executions_owner_created",
        "autopilot_executions",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_autopilot_executions_repository_asset_id",
        "autopilot_executions",
        ["repository_asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_executions_repository_asset_id", table_name="autopilot_executions")
    op.drop_index("ix_autopilot_executions_owner_created", table_name="autopilot_executions")
    op.drop_index("ix_autopilot_executions_job_created", table_name="autopilot_executions")
    op.drop_table("autopilot_executions")
