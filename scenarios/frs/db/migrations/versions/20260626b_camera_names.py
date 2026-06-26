"""persistent camera id -> name map

Revision ID: 20260626b_camera_names
Revises: 20260626_report_schedules
"""
from alembic import op
import sqlalchemy as sa

revision = "20260626b_camera_names"
down_revision = "20260626_report_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frs_camera_names",
        sa.Column("camera_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("frs_camera_names")
