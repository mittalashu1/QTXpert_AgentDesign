"""Persist non-secret Autopilot test setup references.

Revision ID: 0016_autopilot_setup_profile
Revises: 0015_execution_mobile_targets
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_autopilot_setup_profile"
down_revision: Union[str, Sequence[str], None] = "0015_execution_mobile_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autopilot_jobs", sa.Column("setup_profile", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("autopilot_jobs", "setup_profile")
