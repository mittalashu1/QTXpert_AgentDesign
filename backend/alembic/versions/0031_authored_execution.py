"""Carry authored automation and fixture references into execution results."""
from alembic import op
import sqlalchemy as sa

revision = "0031_authored_execution"
down_revision = "0030_local_autopilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("automation", sa.JSON(), nullable=True))
    op.add_column("execution_plan_cases", sa.Column("automation", sa.JSON(), nullable=True))
    op.add_column("execution_plans", sa.Column("fixture_bindings", sa.JSON(), nullable=True))
    op.add_column("execution_results", sa.Column("execution_spec", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("execution_results", "execution_spec")
    op.drop_column("execution_plans", "fixture_bindings")
    op.drop_column("execution_plan_cases", "automation")
    op.drop_column("test_cases", "automation")
