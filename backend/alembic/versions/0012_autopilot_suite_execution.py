"""Persist latest autonomous safe-suite result for Autopilot jobs.

Revision ID: 0012_autopilot_suite_execution
Revises: 0011_autopilot_discovery
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012_autopilot_suite_execution"
down_revision: Union[str, Sequence[str], None] = "0011_autopilot_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autopilot_jobs", sa.Column("suite_execution", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("autopilot_jobs", "suite_execution")
