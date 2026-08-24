"""Persist a user-facing title for each generated test set.

Revision ID: 0006_generation_run_title
Revises: 0005_execution
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_generation_run_title"
down_revision: Union[str, Sequence[str], None] = "0005_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("title", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_runs", "title")

