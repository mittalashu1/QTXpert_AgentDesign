"""M4 Playwright execution and embedded defect logging.

Revision ID: 0005_execution
Revises: 0004_generation_profile
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_execution"
down_revision = "0004_generation_profile"
branch_labels = None
depends_on = None

execution_status = postgresql.ENUM("queued", "running", "completed", "failed", "cancelled", name="execution_status", create_type=False)
result_status = postgresql.ENUM("pending", "passed", "failed", "blocked", "skipped", name="execution_result_status", create_type=False)
defect_status = postgresql.ENUM("open", "in_progress", "resolved", "closed", name="defect_status", create_type=False)

def upgrade() -> None:
    postgresql.ENUM("queued", "running", "completed", "failed", "cancelled", name="execution_status").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM("pending", "passed", "failed", "blocked", "skipped", name="execution_result_status").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM("open", "in_progress", "resolved", "closed", name="defect_status").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "execution_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", execution_status, nullable=False),
        sa.Column("browser", sa.String(20), nullable=False),
        sa.Column("base_url", sa.String(2048), nullable=False),
        sa.Column("total_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocked_tests", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_runs_project_id", "execution_runs", ["project_id"])
    op.create_table(
        "execution_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_cases.id"), nullable=False),
        sa.Column("status", result_status, nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error_message", sa.Text),
        sa.Column("evidence", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_results_execution_run_id", "execution_results", ["execution_run_id"])
    op.create_table(
        "defects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("execution_results.id", ondelete="CASCADE"), nullable=False),
        sa.Column("defect_key", sa.String(50), nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("severity", sa.String(30), nullable=False),
        sa.Column("status", defect_status, nullable=False),
        sa.Column("logged_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_defects_execution_result_id", "defects", ["execution_result_id"])

def downgrade() -> None:
    op.drop_table("defects")
    op.drop_table("execution_results")
    op.drop_table("execution_runs")
    defect_status.drop(op.get_bind(), checkfirst=True)
    result_status.drop(op.get_bind(), checkfirst=True)
    execution_status.drop(op.get_bind(), checkfirst=True)

