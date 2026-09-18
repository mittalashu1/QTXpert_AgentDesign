"""Persist Autopilot context sources and the shared Test Design hand-off."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0028_autopilot_context_sources"
down_revision: Union[str, Sequence[str], None] = "0027_autopilot_workflow_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The shared generation run is created only when the user approves cases;
    # keeping it nullable preserves existing Autopilot jobs and makes retries
    # idempotent.
    op.add_column(
        "autopilot_jobs",
        sa.Column("shared_generation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_autopilot_jobs_shared_generation_run_id",
        "autopilot_jobs",
        ["shared_generation_run_id"],
    )
    op.create_foreign_key(
        "fk_autopilot_jobs_shared_generation_run_id",
        "autopilot_jobs",
        "generation_runs",
        ["shared_generation_run_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "autopilot_context_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("autopilot_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("trust_level", sa.String(length=12), nullable=False, server_default="medium"),
        sa.Column("observed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("influenced_plan_items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("influenced_test_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["autopilot_job_id"], ["autopilot_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autopilot_job_id", "source_id", name="uq_autopilot_context_sources_job_source"),
    )
    op.create_index(
        "ix_autopilot_context_sources_autopilot_job_id",
        "autopilot_context_sources",
        ["autopilot_job_id"],
    )
    op.create_index(
        "ix_autopilot_context_sources_job_id",
        "autopilot_context_sources",
        ["job_id"],
    )
    op.create_index(
        "ix_autopilot_context_sources_owner_project",
        "autopilot_context_sources",
        ["owner_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_context_sources_owner_project", table_name="autopilot_context_sources")
    op.drop_index("ix_autopilot_context_sources_job_id", table_name="autopilot_context_sources")
    op.drop_index("ix_autopilot_context_sources_autopilot_job_id", table_name="autopilot_context_sources")
    op.drop_table("autopilot_context_sources")
    op.drop_constraint("fk_autopilot_jobs_shared_generation_run_id", "autopilot_jobs", type_="foreignkey")
    op.drop_index("ix_autopilot_jobs_shared_generation_run_id", table_name="autopilot_jobs")
    op.drop_column("autopilot_jobs", "shared_generation_run_id")

