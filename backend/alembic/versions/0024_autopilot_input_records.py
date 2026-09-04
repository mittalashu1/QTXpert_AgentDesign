"""Add encrypted Autopilot checkpoint input records."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0024_autopilot_input_records"
down_revision: Union[str, Sequence[str], None] = "0023_execution_plan_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autopilot_input_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("surface_key", sa.String(length=128), nullable=False),
        sa.Column("input_key", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False, server_default="test_data"),
        sa.Column("decision", sa.String(length=20), nullable=False, server_default="provide"),
        sa.Column("save_for_reuse", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("encrypted_value", sa.Text(), nullable=True),
        sa.Column("generator_spec", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_autopilot_input_records_owner_id",
        "autopilot_input_records",
        ["owner_id"],
    )
    op.create_index(
        "ix_autopilot_input_records_project_id",
        "autopilot_input_records",
        ["project_id"],
    )
    op.create_index(
        "ix_autopilot_input_records_job_id",
        "autopilot_input_records",
        ["job_id"],
    )
    op.create_index(
        "ix_autopilot_input_records_surface_key",
        "autopilot_input_records",
        ["surface_key"],
    )
    op.create_index(
        "ix_autopilot_input_records_scope_key",
        "autopilot_input_records",
        ["owner_id", "project_id", "surface_key", "input_key", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_input_records_scope_key", table_name="autopilot_input_records")
    op.drop_index("ix_autopilot_input_records_surface_key", table_name="autopilot_input_records")
    op.drop_index("ix_autopilot_input_records_job_id", table_name="autopilot_input_records")
    op.drop_index("ix_autopilot_input_records_project_id", table_name="autopilot_input_records")
    op.drop_index("ix_autopilot_input_records_owner_id", table_name="autopilot_input_records")
    op.drop_table("autopilot_input_records")
