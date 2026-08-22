"""Merge the security and Test Design Alembic migration heads.

Revision ID: 0003_merge_migration_heads
Revises: 0002_add_user_token_version, 0002_test_design_hardening
"""
from typing import Sequence, Union


revision: str = "0003_merge_migration_heads"
down_revision: Union[str, Sequence[str], None] = (
    "0002_add_user_token_version",
    "0002_test_design_hardening",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # This merge revision intentionally changes no database objects.
    pass


def downgrade() -> None:
    pass
