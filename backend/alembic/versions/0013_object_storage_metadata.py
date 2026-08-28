"""Add object-store metadata for uploaded artifacts.

The existing ``uploaded_asset_chunks`` table remains intact for backwards
compatibility.  New object-store backed assets reference ``object_key`` and do
not create binary chunk rows; a later, checksum-verified migration can remove
legacy chunks safely.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_object_storage_metadata"
down_revision: Union[str, Sequence[str], None] = (
    "0012_autopilot_suite_execution",
    "0011_autopilot_execution_history",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uploaded_assets",
        sa.Column("object_key", sa.String(length=1024), nullable=True),
    )
    op.create_index(
        "ix_uploaded_assets_object_key",
        "uploaded_assets",
        ["object_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_uploaded_assets_object_key", table_name="uploaded_assets")
    op.drop_column("uploaded_assets", "object_key")
