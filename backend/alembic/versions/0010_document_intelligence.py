"""AI Document Intelligence runs and evidence-backed findings.

Revision ID: 0010_document_intelligence
Revises: 0009_upload_repository
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010_document_intelligence"
down_revision: Union[str, Sequence[str], None] = "0009_upload_repository"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("profile", sa.String(length=40), nullable=False, server_default="general"),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("document_inventory", sa.JSON(), nullable=True),
        sa.Column("knowledge_model", sa.JSON(), nullable=True),
        sa.Column("scores", sa.JSON(), nullable=True),
        sa.Column("missing_documents", sa.JSON(), nullable=True),
        sa.Column("recommendations", sa.JSON(), nullable=True),
        sa.Column("readiness_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("readiness_status", sa.String(length=40), nullable=False, server_default="not_analyzed"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("published_requirement_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("requirements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_analysis_project_created", "document_analysis_runs", ["project_id", "created_at"])
    op.create_index("ix_document_analysis_requester_created", "document_analysis_runs", ["requested_by_id", "created_at"])

    op.create_table(
        "document_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploaded_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("finding_key", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="medium"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("testing_impact", sa.Text(), nullable=True),
        sa.Column("original_text", sa.Text(), nullable=True),
        sa.Column("suggested_refinement", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="open"),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_document_findings_run_severity", "document_findings", ["run_id", "severity"])
    op.create_index("ix_document_findings_asset", "document_findings", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_document_findings_asset", table_name="document_findings")
    op.drop_index("ix_document_findings_run_severity", table_name="document_findings")
    op.drop_table("document_findings")
    op.drop_index("ix_document_analysis_requester_created", table_name="document_analysis_runs")
    op.drop_index("ix_document_analysis_project_created", table_name="document_analysis_runs")
    op.drop_table("document_analysis_runs")
