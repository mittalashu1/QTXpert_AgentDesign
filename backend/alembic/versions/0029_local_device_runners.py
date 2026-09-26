"""Add outbound local device runner enrollment and leases."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0029_local_device_runners"
down_revision: Union[str, Sequence[str], None] = "0028_autopilot_context_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_device_runners",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("enrollment_token_hash", sa.String(length=64), nullable=True),
        sa.Column("enrollment_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("runner_token_hash", sa.String(length=64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_local_device_runners_owner_id", "local_device_runners", ["owner_id"])
    op.create_index("ix_local_device_runners_project_id", "local_device_runners", ["project_id"])
    op.create_index("ix_local_device_runners_status", "local_device_runners", ["status"])

    op.create_table(
        "local_runner_jobs",
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("runner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("lease_token_hash", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["execution_run_id"], ["execution_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["runner_id"], ["local_device_runners.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("execution_run_id"),
    )
    op.create_index("ix_local_runner_jobs_runner_id", "local_runner_jobs", ["runner_id"])
    op.create_index("ix_local_runner_jobs_status", "local_runner_jobs", ["status"])
    op.create_index("ix_local_runner_jobs_lease_expires_at", "local_runner_jobs", ["lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_local_runner_jobs_lease_expires_at", table_name="local_runner_jobs")
    op.drop_index("ix_local_runner_jobs_status", table_name="local_runner_jobs")
    op.drop_index("ix_local_runner_jobs_runner_id", table_name="local_runner_jobs")
    op.drop_table("local_runner_jobs")
    op.drop_index("ix_local_device_runners_status", table_name="local_device_runners")
    op.drop_index("ix_local_device_runners_project_id", table_name="local_device_runners")
    op.drop_index("ix_local_device_runners_owner_id", table_name="local_device_runners")
    op.drop_table("local_device_runners")
