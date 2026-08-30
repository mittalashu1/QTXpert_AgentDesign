"""Add profile/build scoped identities to Autopilot jobs."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_autopilot_surfaces"
down_revision: Union[str, Sequence[str], None] = "0018_autopilot_document_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autopilot_jobs",
        sa.Column("profile_id", sa.String(length=80), nullable=False, server_default="uae_fintech"),
    )
    op.add_column(
        "autopilot_jobs",
        sa.Column("surface_key", sa.String(length=64), nullable=False, server_default=""),
    )
    op.add_column(
        "autopilot_jobs",
        sa.Column("surface_identity", sa.String(length=500), nullable=False, server_default=""),
    )
    op.add_column(
        "autopilot_jobs",
        sa.Column("surface_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_autopilot_jobs_surface_key", "autopilot_jobs", ["surface_key"])


def downgrade() -> None:
    op.drop_index("ix_autopilot_jobs_surface_key", table_name="autopilot_jobs")
    op.drop_column("autopilot_jobs", "surface_version")
    op.drop_column("autopilot_jobs", "surface_identity")
    op.drop_column("autopilot_jobs", "surface_key")
    op.drop_column("autopilot_jobs", "profile_id")
