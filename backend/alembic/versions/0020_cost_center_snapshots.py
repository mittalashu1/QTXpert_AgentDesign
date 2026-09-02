"""Persist non-sensitive Cost Center provider refresh snapshots."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020_cost_center_snapshots"
down_revision: Union[str, Sequence[str], None] = "0019_autopilot_surfaces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_center_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="unavailable"),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cost_center_snapshots_scope",
        "cost_center_snapshots",
        ["scope"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_cost_center_snapshots_scope", table_name="cost_center_snapshots")
    op.drop_table("cost_center_snapshots")
