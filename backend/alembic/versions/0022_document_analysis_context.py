"""Persist the redacted Document Intelligence scope context."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022_document_analysis_context"
down_revision: Union[str, Sequence[str], None] = "0021_document_intelligence_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_analysis_runs",
        sa.Column("additional_context", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_analysis_runs", "additional_context")

