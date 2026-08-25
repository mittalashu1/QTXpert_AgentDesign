"""Persist LLM usage for the admin cost dashboard.

Revision ID: 0007_llm_usage_events
Revises: 0006_generation_run_title
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0007_llm_usage_events"
down_revision: Union[str, Sequence[str], None] = "0006_generation_run_title"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=30), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=18, scale=10), nullable=True),
    )
    op.create_index(
        "ix_llm_usage_events_created_at", "llm_usage_events", ["created_at"]
    )
    op.create_index(
        "ix_llm_usage_events_provider_model",
        "llm_usage_events",
        ["provider", "model"],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_usage_events_provider_model", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_created_at", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")
