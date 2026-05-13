"""fix recordings schema: rename duration_seconds to duration, fps to float

Revision ID: 005_fix_recordings_schema
Revises: 004_fix_settings_notifications
Create Date: 2026-03-06 14:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "005_fix_recordings_schema"
down_revision = "004_fix_settings_notifications"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.alter_column("duration_seconds", new_column_name="duration")
        batch.alter_column(
            "fps",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("recordings") as batch:
        batch.alter_column(
            "fps",
            existing_type=sa.Float(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
        batch.alter_column("duration", new_column_name="duration_seconds")
