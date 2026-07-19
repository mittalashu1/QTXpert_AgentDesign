"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-18 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "admin", "qa_lead", "qa_engineer", "business_analyst",
                "automation_engineer", "viewer", name="user_role",
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("is_sso_user", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("entra_object_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("external_key", sa.String(100), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "brd_upload", "jira_export", "jira_live", "confluence",
                "direct_prompt", name="requirement_source",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("received", "normalized", "failed", name="requirement_status"),
            nullable=False,
        ),
        sa.Column("raw_content", sa.Text, nullable=False),
        sa.Column("normalized_content", sa.Text, nullable=True),
        sa.Column("extracted_metadata", sa.JSON, nullable=True),
        sa.Column("source_file_path", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "requested_by_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"), nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "normalizing", "analyzing", "generating_scenarios",
                "generating_test_cases", "risk_analysis", "completed", "failed",
                name="run_status",
            ),
            nullable=False,
        ),
        sa.Column("llm_provider", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("requirement_summary", sa.String, nullable=True),
        sa.Column("business_rules", sa.JSON, nullable=True),
        sa.Column("functional_breakdown", sa.JSON, nullable=True),
        sa.Column("test_scenarios", sa.JSON, nullable=True),
        sa.Column("risk_analysis", sa.JSON, nullable=True),
        sa.Column("processing_time_seconds", sa.Float, nullable=True),
        sa.Column("error_message", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "test_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "generation_run_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_runs.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "requirement_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requirements.id"), nullable=True,
        ),
        sa.Column("test_case_key", sa.String(50), nullable=False),
        sa.Column("requirement_traceability", sa.String(255), nullable=True),
        sa.Column(
            "test_type",
            sa.Enum(
                "functional", "negative", "boundary", "integration", "api", "database",
                "security", "accessibility", "usability", "performance", "regression",
                "exploratory", "data_validation", "workflow", "role_based", "permission",
                "maker_checker", "error_handling", "localization",
                "browser_compatibility", "mobile", "cross_platform",
                name="test_case_type",
            ),
            nullable=False,
        ),
        sa.Column("scenario", sa.String(500), nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column(
            "priority", sa.Enum("critical", "high", "medium", "low", name="priority"),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum("blocker", "critical", "major", "minor", "trivial", name="severity"),
            nullable=False,
        ),
        sa.Column("preconditions", sa.Text, nullable=True),
        sa.Column("test_data", sa.JSON, nullable=True),
        sa.Column("steps", sa.JSON, nullable=False),
        sa.Column("expected_result", sa.Text, nullable=False),
        sa.Column("post_conditions", sa.Text, nullable=True),
        sa.Column("is_automation_candidate", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("automation_type", sa.String(100), nullable=True),
        sa.Column(
            "risk_level", sa.Enum("high", "medium", "low", name="risk_level"),
            nullable=False, server_default="medium",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "api_configurations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("llm_provider", sa.String(50), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("extra_settings", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("detail", sa.JSON, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("api_configurations")
    op.drop_table("test_cases")
    op.drop_table("generation_runs")
    op.drop_table("requirements")
    op.drop_table("projects")
    op.drop_table("users")
    for enum_name in (
        "test_case_type", "priority", "severity", "risk_level", "run_status",
        "requirement_source", "requirement_status", "user_role",
    ):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
