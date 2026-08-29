"""Add web/mobile target metadata to execution runs."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015_execution_mobile_targets"
down_revision: Union[str, Sequence[str], None] = "0014_execution_plans"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Mobile targets do not have a URL. Existing web runs remain unchanged.
    op.alter_column(
        "execution_runs",
        "base_url",
        existing_type=sa.String(length=2048),
        nullable=True,
    )
    op.add_column(
        "execution_runs",
        sa.Column("target_kind", sa.String(length=20), nullable=False, server_default="web"),
    )
    op.add_column(
        "execution_runs",
        sa.Column("provider", sa.String(length=30), nullable=False, server_default="playwright"),
    )
    op.add_column(
        "execution_runs",
        sa.Column(
            "app_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("execution_runs", sa.Column("device_name", sa.String(length=120), nullable=True))
    op.add_column("execution_runs", sa.Column("platform_version", sa.String(length=40), nullable=True))
    op.add_column("execution_runs", sa.Column("appium_url", sa.String(length=2048), nullable=True))
    op.add_column("execution_runs", sa.Column("appium_app", sa.String(length=2048), nullable=True))
    op.add_column("execution_runs", sa.Column("target_metadata", sa.JSON(), nullable=True))
    op.create_index("ix_execution_runs_app_asset_id", "execution_runs", ["app_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_execution_runs_app_asset_id", table_name="execution_runs")
    op.drop_column("execution_runs", "target_metadata")
    op.drop_column("execution_runs", "appium_app")
    op.drop_column("execution_runs", "appium_url")
    op.drop_column("execution_runs", "platform_version")
    op.drop_column("execution_runs", "device_name")
    op.drop_column("execution_runs", "app_asset_id")
    op.drop_column("execution_runs", "provider")
    op.drop_column("execution_runs", "target_kind")
    op.alter_column(
        "execution_runs",
        "base_url",
        existing_type=sa.String(length=2048),
        nullable=False,
    )

