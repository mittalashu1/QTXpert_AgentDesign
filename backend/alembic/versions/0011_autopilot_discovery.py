"""Persist Runtime Discovery results for Autopilot jobs.

Revision ID: 0011_autopilot_discovery
Revises: 0010_document_intelligence
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011_autopilot_discovery"
down_revision: Union[str, Sequence[str], None] = "0010_document_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autopilot_jobs", sa.Column("discovery", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("autopilot_jobs", "discovery")
