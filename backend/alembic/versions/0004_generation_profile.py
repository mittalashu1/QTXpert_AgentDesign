"""Persist the AI release profile selected for each generation run."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_generation_profile"
down_revision: Union[str, Sequence[str], None] = "0003_merge_migration_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("generation_profile", sa.String(length=30), nullable=False, server_default="feature"),
    )
    op.alter_column("generation_runs", "generation_profile", server_default=None)


def downgrade() -> None:
    op.drop_column("generation_runs", "generation_profile")
