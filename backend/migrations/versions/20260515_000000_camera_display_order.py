"""
Camera display_order — operator-controlled drag-to-reorder

Revision ID: camera_display_order
Revises: phase10_ai_schema
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa


revision = "camera_display_order"
down_revision = "phase10_ai_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cameras",
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_cameras_display_order", "cameras", ["display_order"]
    )


def downgrade():
    op.drop_index("ix_cameras_display_order", table_name="cameras")
    op.drop_column("cameras", "display_order")
