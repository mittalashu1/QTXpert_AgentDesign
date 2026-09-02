"""Add safe setup references for guided execution preflight."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_execution_plan_inputs"
down_revision: Union[str, Sequence[str], None] = "0022_document_analysis_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "execution_plans",
        sa.Column("runtime_inputs", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_plans", "runtime_inputs")
