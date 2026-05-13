"""Fix settings schema + create notification tables

Revision ID: 004_fix_settings_notifications
Revises: 003_fix_roles_schema
Create Date: 2026-03-06

Changes:
  - settings: add value_type, description columns (key is already PK, is_sensitive already exists)
  - webhook_configs and notification_logs already exist in DB — no action needed
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_fix_settings_notifications"
down_revision: Union[str, None] = "003_fix_roles_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Settings: add missing columns ───────────────────────────────────
    op.add_column(
        "settings",
        sa.Column("value_type", sa.String(length=20), nullable=True, server_default="string"),
    )
    op.add_column(
        "settings",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("settings", "description")
    op.drop_column("settings", "value_type")
