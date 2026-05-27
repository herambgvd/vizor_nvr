"""add bandwidth_alert_threshold_pct to cameras

Revision ID: 20260528_050000
Revises: 20260527_010000
Create Date: 2026-05-28

Adds cameras.bandwidth_alert_threshold_pct INTEGER DEFAULT 80.
(bandwidth_limit_kbps already exists in the schema from a prior migration.)
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_050000"
down_revision = "20260527_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "bandwidth_alert_threshold_pct" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column(
                    "bandwidth_alert_threshold_pct",
                    sa.Integer(),
                    nullable=False,
                    server_default="80",
                )
            )
    # bandwidth_limit_kbps is already present; ensure it exists idempotently
    if "bandwidth_limit_kbps" not in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.add_column(
                sa.Column(
                    "bandwidth_limit_kbps",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("cameras")}
    if "bandwidth_alert_threshold_pct" in existing_cols:
        with op.batch_alter_table("cameras") as batch:
            batch.drop_column("bandwidth_alert_threshold_pct")
