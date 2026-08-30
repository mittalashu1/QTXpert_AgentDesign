"""Add unified website and mobile target metadata to Autopilot jobs."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_autopilot_runtime_targets"
down_revision: Union[str, Sequence[str], None] = "0016_autopilot_setup_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "autopilot_jobs",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_autopilot_jobs_project_id", "autopilot_jobs", ["project_id"])
    op.add_column(
        "autopilot_jobs",
        sa.Column("target_kind", sa.String(length=20), nullable=False, server_default="android"),
    )
    op.add_column("autopilot_jobs", sa.Column("target_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("autopilot_jobs", "target_url")
    op.drop_column("autopilot_jobs", "target_kind")
    op.drop_index("ix_autopilot_jobs_project_id", table_name="autopilot_jobs")
    op.drop_column("autopilot_jobs", "project_id")
