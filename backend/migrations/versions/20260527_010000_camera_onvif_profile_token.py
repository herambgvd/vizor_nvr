"""add onvif_profile_token to cameras

Revision ID: 20260527_010000
Revises: 20260527_000000
Create Date: 2026-05-27

Adds a nullable cameras.onvif_profile_token VARCHAR(256) column so that
each camera row remembers which ONVIF media profile (channel) it
represents when the device is an NVR/DVR exposing multiple cameras
through a single ONVIF endpoint.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260527_010000"
down_revision = "20260527_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "onvif_profile_token" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column("onvif_profile_token", sa.String(256), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "onvif_profile_token" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("onvif_profile_token")
