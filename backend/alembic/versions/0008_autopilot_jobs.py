"""Persist Autopilot job state and generated analysis across deployments.

Revision ID: 0008_autopilot_jobs
Revises: 0007_llm_usage_events
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0008_autopilot_jobs"
down_revision: Union[str, Sequence[str], None] = "0007_llm_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autopilot_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column("apk_path", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="uploaded"),
        sa.Column("stage", sa.String(length=80), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_autopilot_jobs_job_id", "autopilot_jobs", ["job_id"], unique=True)
    op.create_index(
        "ix_autopilot_jobs_owner_created", "autopilot_jobs", ["owner_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_jobs_owner_created", table_name="autopilot_jobs")
    op.drop_index("ix_autopilot_jobs_job_id", table_name="autopilot_jobs")
    op.drop_table("autopilot_jobs")
