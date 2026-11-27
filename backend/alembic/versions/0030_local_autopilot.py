"""Add outbound paired Android discovery and suite sessions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0030_local_autopilot"
down_revision = "0029_local_device_runners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_autopilot_sessions",
        sa.Column("runner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("local_device_runners.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploaded_assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_name", sa.String(120), nullable=False),
        sa.Column("package_name", sa.String(300), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("worker_id", postgresql.UUID(as_uuid=True)),
        sa.Column("command_id", postgresql.UUID(as_uuid=True)),
        sa.Column("command_payload", sa.Text()),
        sa.Column("command_delivered", sa.Boolean(), nullable=False),
        sa.Column("command_answer", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("local_autopilot_sessions")
