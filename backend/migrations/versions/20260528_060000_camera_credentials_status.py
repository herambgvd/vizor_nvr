"""add credentials_status and credentials_checked_at to cameras

Revision ID: 20260528_060000
Revises: 20260529_000000
Create Date: 2026-05-28

Adds cameras.credentials_status VARCHAR(20) NULL and
cameras.credentials_checked_at TIMESTAMP NULL.
Idempotent — safe to run multiple times.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_060000"
down_revision = "20260529_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}

    if "credentials_status" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column(
                    "credentials_status",
                    sa.String(20),
                    nullable=True,
                    server_default=None,
                )
            )

    if "credentials_checked_at" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column(
                    "credentials_checked_at",
                    sa.DateTime(),
                    nullable=True,
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}

    if "credentials_checked_at" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("credentials_checked_at")

    if "credentials_status" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("credentials_status")
