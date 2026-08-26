"""Central durable upload repository for Design and Autopilot assets.

Revision ID: 0009_upload_repository
Revises: 0008_autopilot_jobs
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_upload_repository"
down_revision: Union[str, Sequence[str], None] = "0008_autopilot_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploaded_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="other"),
        sa.Column("source_module", sa.String(length=80), nullable=False, server_default="repository"),
        sa.Column("storage_backend", sa.String(length=30), nullable=False, server_default="postgres_chunks"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_uploaded_assets_owner_created",
        "uploaded_assets",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_uploaded_assets_owner_category",
        "uploaded_assets",
        ["owner_id", "category"],
    )
    op.create_index(
        "ix_uploaded_assets_project_created",
        "uploaded_assets",
        ["project_id", "created_at"],
    )

    op.create_table(
        "uploaded_asset_chunks",
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploaded_assets.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_uploaded_asset_chunks_asset_order",
        "uploaded_asset_chunks",
        ["asset_id", "chunk_index"],
    )

    op.add_column(
        "autopilot_jobs",
        sa.Column("repository_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_autopilot_jobs_repository_asset_id",
        "autopilot_jobs",
        "uploaded_assets",
        ["repository_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_autopilot_jobs_repository_asset_id",
        "autopilot_jobs",
        ["repository_asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_jobs_repository_asset_id", table_name="autopilot_jobs")
    op.drop_constraint(
        "fk_autopilot_jobs_repository_asset_id",
        "autopilot_jobs",
        type_="foreignkey",
    )
    op.drop_column("autopilot_jobs", "repository_asset_id")
    op.drop_index("ix_uploaded_asset_chunks_asset_order", table_name="uploaded_asset_chunks")
    op.drop_table("uploaded_asset_chunks")
    op.drop_index("ix_uploaded_assets_project_created", table_name="uploaded_assets")
    op.drop_index("ix_uploaded_assets_owner_category", table_name="uploaded_assets")
    op.drop_index("ix_uploaded_assets_owner_created", table_name="uploaded_assets")
    op.drop_table("uploaded_assets")
