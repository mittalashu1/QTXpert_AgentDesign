"""Harden test-design persistence.

Revision ID: 0002_test_design_hardening
Revises: 0001_initial
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0002_test_design_hardening"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_test_cases_run_key", "test_cases", ["generation_run_id", "test_case_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_test_cases_run_key", "test_cases", type_="unique")

