"""Add versioned Test Design to Test Execution plans and snapshots."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_execution_plans"
down_revision: Union[str, Sequence[str], None] = "0013_object_storage_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "execution_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_generation_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("generation_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("suite_type", sa.String(30), nullable=False, server_default="regression"),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("source_title", sa.String(500), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_plans_project_id", "execution_plans", ["project_id"])
    op.create_index("ix_execution_plans_source_generation_run_id", "execution_plans", ["source_generation_run_id"])

    op.create_table(
        "execution_plan_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_test_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("selection_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("selected", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("execution_mode", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("readiness", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("blocker_reason", sa.Text, nullable=True),
        sa.Column("test_case_key", sa.String(50), nullable=False),
        sa.Column("requirement_traceability", sa.String(255), nullable=True),
        sa.Column("test_type", sa.String(50), nullable=False),
        sa.Column("scenario", sa.String(500), nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column("priority", sa.String(30), nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("preconditions", sa.Text, nullable=True),
        sa.Column("test_data", sa.JSON, nullable=True),
        sa.Column("steps", sa.JSON, nullable=False),
        sa.Column("expected_result", sa.Text, nullable=False),
        sa.Column("post_conditions", sa.Text, nullable=True),
        sa.Column("is_automation_candidate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("automation_type", sa.String(100), nullable=True),
        sa.Column("risk_level", sa.String(30), nullable=False, server_default="medium"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_plan_cases_plan_id", "execution_plan_cases", ["plan_id"])
    op.create_index("ix_execution_plan_cases_source_test_case_id", "execution_plan_cases", ["source_test_case_id"])

    op.add_column(
        "execution_runs",
        sa.Column("execution_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_plans.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_execution_runs_execution_plan_id", "execution_runs", ["execution_plan_id"])
    op.add_column(
        "execution_results",
        sa.Column("execution_plan_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_plan_cases.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_execution_results_execution_plan_case_id", "execution_results", ["execution_plan_case_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_results_execution_plan_case_id", table_name="execution_results")
    op.drop_column("execution_results", "execution_plan_case_id")
    op.drop_index("ix_execution_runs_execution_plan_id", table_name="execution_runs")
    op.drop_column("execution_runs", "execution_plan_id")
    op.drop_index("ix_execution_plan_cases_source_test_case_id", table_name="execution_plan_cases")
    op.drop_index("ix_execution_plan_cases_plan_id", table_name="execution_plan_cases")
    op.drop_table("execution_plan_cases")
    op.drop_index("ix_execution_plans_source_generation_run_id", table_name="execution_plans")
    op.drop_index("ix_execution_plans_project_id", table_name="execution_plans")
    op.drop_table("execution_plans")

