"""add retention_days to cameras

Revision ID: 20260528_020000
Revises: 20260527_010000
Create Date: 2026-05-28

Adds a nullable cameras.retention_days INTEGER column.
NULL means "use global retention setting"; non-null overrides it per camera.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_020000"
down_revision = "20260528_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "retention_days" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column("retention_days", sa.Integer(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "retention_days" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("retention_days")
