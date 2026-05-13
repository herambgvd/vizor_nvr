"""Phase 6 — Access control

Revision ID: 014_phase6_access_control
Revises: 013_phase5_security_compliance
Create Date: 2026-03-16 00:00:00

Adds:
  6.3  Direct per-user camera ACL — user_camera_access table
       (user_groups + group_camera_access already covered by the existing
       CameraGroup + user_camera_groups schema from earlier phases)
"""
from alembic import op
import sqlalchemy as sa


revision = "014_phase6_access_control"
down_revision = "013_phase5_security_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_camera_access",
        sa.Column("user_id", sa.String(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("camera_id", sa.String(),
                  sa.ForeignKey("cameras.id", ondelete="CASCADE"),
                  primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("user_camera_access")
