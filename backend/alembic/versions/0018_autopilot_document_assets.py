"""Persist repository document attachments on Autopilot jobs."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_autopilot_document_assets"
down_revision: Union[str, Sequence[str], None] = "0017_autopilot_runtime_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("autopilot_jobs", sa.Column("document_asset_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("autopilot_jobs", "document_asset_ids")
