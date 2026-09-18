"""Persist the Autopilot workflow, plan and observed application map."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0027_autopilot_workflow_contract"
down_revision: Union[str, Sequence[str], None] = "0026_integration_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autopilot_jobs",
        sa.Column("phase", sa.String(length=40), nullable=False, server_default="draft"),
    )
    op.add_column("autopilot_jobs", sa.Column("plan", sa.JSON(), nullable=True))
    op.add_column("autopilot_jobs", sa.Column("application_map", sa.JSON(), nullable=True))
    op.add_column("autopilot_jobs", sa.Column("case_reviews", sa.JSON(), nullable=True))

    op.create_table(
        "autopilot_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("autopilot_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending_review"),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["autopilot_job_id"], ["autopilot_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autopilot_job_id", "version", name="uq_autopilot_plans_job_version"),
    )
    op.create_index("ix_autopilot_plans_autopilot_job_id", "autopilot_plans", ["autopilot_job_id"])
    op.create_index("ix_autopilot_plans_job_id", "autopilot_plans", ["job_id"])
    op.create_index("ix_autopilot_plans_owner_project", "autopilot_plans", ["owner_id", "project_id"])

    op.create_table(
        "autopilot_application_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("autopilot_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("map", sa.JSON(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["autopilot_job_id"], ["autopilot_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("autopilot_job_id", "version", name="uq_autopilot_application_maps_job_version"),
    )
    op.create_index(
        "ix_autopilot_application_maps_autopilot_job_id",
        "autopilot_application_maps",
        ["autopilot_job_id"],
    )
    op.create_index(
        "ix_autopilot_application_maps_job_version",
        "autopilot_application_maps",
        ["autopilot_job_id", "version"],
    )
    op.create_index(
        "ix_autopilot_application_maps_owner_project",
        "autopilot_application_maps",
        ["owner_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_application_maps_owner_project", table_name="autopilot_application_maps")
    op.drop_index("ix_autopilot_application_maps_job_version", table_name="autopilot_application_maps")
    op.drop_index("ix_autopilot_application_maps_autopilot_job_id", table_name="autopilot_application_maps")
    op.drop_table("autopilot_application_maps")
    op.drop_index("ix_autopilot_plans_owner_project", table_name="autopilot_plans")
    op.drop_index("ix_autopilot_plans_job_id", table_name="autopilot_plans")
    op.drop_index("ix_autopilot_plans_autopilot_job_id", table_name="autopilot_plans")
    op.drop_table("autopilot_plans")
    op.drop_column("autopilot_jobs", "application_map")
    op.drop_column("autopilot_jobs", "plan")
    op.drop_column("autopilot_jobs", "case_reviews")
    op.drop_column("autopilot_jobs", "phase")

