"""Phase 5 — notification webhook configs and delivery logs

Revision ID: 009_phase5_notifications
Revises: 008_phase4_onvif_complete
Create Date: 2026-03-11 00:00:00

Changes:
  - webhook_configs: webhook endpoint configuration table
  - notification_logs: delivery history / audit log table
"""
from alembic import op
import sqlalchemy as sa

revision = "009_phase5_notifications"
down_revision = "008_phase4_onvif_complete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── webhook_configs ──────────────────────────────────────────────────
    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret", sa.String(200), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("camera_ids", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("custom_headers", sa.JSON(), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_configs_is_active", "webhook_configs", ["is_active"])

    # ── notification_logs ────────────────────────────────────────────────
    op.create_table(
        "notification_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("webhook_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_logs_webhook_id", "notification_logs", ["webhook_id"])
    op.create_index("ix_notification_logs_event_type", "notification_logs", ["event_type"])
    op.create_index("ix_notification_logs_status", "notification_logs", ["status"])
    op.create_index("ix_notification_logs_created_at", "notification_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_logs_created_at", table_name="notification_logs")
    op.drop_index("ix_notification_logs_status", table_name="notification_logs")
    op.drop_index("ix_notification_logs_event_type", table_name="notification_logs")
    op.drop_index("ix_notification_logs_webhook_id", table_name="notification_logs")
    op.drop_table("notification_logs")

    op.drop_index("ix_webhook_configs_is_active", table_name="webhook_configs")
    op.drop_table("webhook_configs")
