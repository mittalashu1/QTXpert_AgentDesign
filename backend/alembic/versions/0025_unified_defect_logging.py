"""Unify defect logging across execution results and Autopilot suites.

Defect records keep a bounded, secret-free execution snapshot and opaque
repository evidence references.  The Jira columns are an integration boundary;
this migration does not create or modify remote Atlassian issues.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025_unified_defect_logging"
down_revision: Union[str, Sequence[str], None] = "0024_autopilot_input_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy defects remain valid; Autopilot-originated defects use the new
    # nullable job/test fields instead of manufacturing an execution result.
    op.alter_column(
        "defects",
        "execution_result_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "defects",
        sa.Column(
            "autopilot_job_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column("defects", sa.Column("autopilot_test_id", sa.String(length=120), nullable=True))
    op.add_column(
        "defects",
        sa.Column("source", sa.String(length=30), nullable=False, server_default="execution_result"),
    )
    op.add_column("defects", sa.Column("test_title", sa.String(length=500), nullable=True))
    op.add_column("defects", sa.Column("test_bucket", sa.String(length=40), nullable=True))
    op.add_column("defects", sa.Column("target_kind", sa.String(length=20), nullable=True))
    op.add_column("defects", sa.Column("provider", sa.String(length=30), nullable=True))
    op.add_column("defects", sa.Column("evidence_assets", sa.JSON(), nullable=True))
    op.add_column("defects", sa.Column("execution_snapshot", sa.JSON(), nullable=True))
    op.add_column(
        "defects",
        sa.Column("integration_provider", sa.String(length=30), nullable=False, server_default="local"),
    )
    op.add_column(
        "defects",
        sa.Column("integration_status", sa.String(length=40), nullable=False, server_default="local"),
    )
    op.add_column("defects", sa.Column("external_issue_key", sa.String(length=120), nullable=True))
    op.add_column("defects", sa.Column("external_issue_url", sa.String(length=2048), nullable=True))
    op.create_foreign_key(
        "fk_defects_autopilot_job_id",
        "defects",
        "autopilot_jobs",
        ["autopilot_job_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_defects_autopilot_job_id", "defects", ["autopilot_job_id"])
    op.create_index("ix_defects_autopilot_test_id", "defects", ["autopilot_test_id"])


def downgrade() -> None:
    op.drop_index("ix_defects_autopilot_test_id", table_name="defects")
    op.drop_index("ix_defects_autopilot_job_id", table_name="defects")
    op.drop_constraint("fk_defects_autopilot_job_id", "defects", type_="foreignkey")
    for column in (
        "external_issue_url",
        "external_issue_key",
        "integration_status",
        "integration_provider",
        "execution_snapshot",
        "evidence_assets",
        "provider",
        "target_kind",
        "test_bucket",
        "test_title",
        "source",
        "autopilot_test_id",
        "autopilot_job_id",
    ):
        op.drop_column("defects", column)
    op.alter_column(
        "defects",
        "execution_result_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
