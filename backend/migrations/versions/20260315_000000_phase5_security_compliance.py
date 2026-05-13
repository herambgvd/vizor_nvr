"""Phase 5 — Security, compliance, sessions

Revision ID: 013_phase5_security_compliance
Revises: 012_phase4_storage_protection
Create Date: 2026-03-15 00:00:00

Adds:
  5.3  TOTP 2FA           — users.totp_secret, totp_enabled, totp_recovery_codes
  5.5  Session metadata   — refresh_tokens.last_seen_at
  5.6  Password policy    — users.password_changed_at, force_password_reset,
                            password_history table
  6.4  Time-bound access  — users.access_schedule
"""
from alembic import op
import sqlalchemy as sa


revision = "013_phase5_security_compliance"
down_revision = "012_phase4_storage_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("totp_secret", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("totp_enabled", sa.Boolean(),
                                   nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("totp_recovery_codes", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("password_changed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("force_password_reset", sa.Boolean(),
                                   nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("access_schedule", sa.JSON(), nullable=True))

    with op.batch_alter_table("refresh_tokens") as batch:
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))

    op.create_table(
        "password_history",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)")),
    )
    op.create_index("ix_password_history_user_changed",
                    "password_history", ["user_id", "changed_at"])


def downgrade() -> None:
    op.drop_index("ix_password_history_user_changed", table_name="password_history")
    op.drop_table("password_history")
    with op.batch_alter_table("refresh_tokens") as batch:
        batch.drop_column("last_seen_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("access_schedule")
        batch.drop_column("force_password_reset")
        batch.drop_column("password_changed_at")
        batch.drop_column("totp_recovery_codes")
        batch.drop_column("totp_enabled")
        batch.drop_column("totp_secret")
