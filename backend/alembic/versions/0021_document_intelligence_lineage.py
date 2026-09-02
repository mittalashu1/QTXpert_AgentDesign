"""Link downstream runs to their Document Intelligence baseline."""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021_document_intelligence_lineage"
down_revision: Union[str, Sequence[str], None] = "0020_cost_center_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_runs",
        sa.Column("source_document_analysis_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_generation_runs_document_analysis",
        "generation_runs",
        "document_analysis_runs",
        ["source_document_analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_generation_runs_source_document_analysis_id",
        "generation_runs",
        ["source_document_analysis_id"],
    )

    op.add_column(
        "autopilot_jobs",
        sa.Column("document_analysis_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_autopilot_jobs_document_analysis",
        "autopilot_jobs",
        "document_analysis_runs",
        ["document_analysis_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_autopilot_jobs_document_analysis_run_id",
        "autopilot_jobs",
        ["document_analysis_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_autopilot_jobs_document_analysis_run_id", table_name="autopilot_jobs")
    op.drop_constraint("fk_autopilot_jobs_document_analysis", "autopilot_jobs", type_="foreignkey")
    op.drop_column("autopilot_jobs", "document_analysis_run_id")
    op.drop_index("ix_generation_runs_source_document_analysis_id", table_name="generation_runs")
    op.drop_constraint("fk_generation_runs_document_analysis", "generation_runs", type_="foreignkey")
    op.drop_column("generation_runs", "source_document_analysis_id")
