"""event lifecycle columns (incident upsert: updated_at, observation_count, duration_s)

Revision ID: ppe_0004_lifecycle
Revises: ppe_0003_reports
"""
from alembic import op
import sqlalchemy as sa

revision = "ppe_0004_lifecycle"
down_revision = "ppe_0003_reports"
branch_labels = None
depends_on = None


def _cols(table: str) -> set:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    have = _cols("ppe_events")
    if "updated_at" not in have:
        op.add_column("ppe_events", sa.Column("updated_at", sa.DateTime(), nullable=True))
    if "observation_count" not in have:
        op.add_column("ppe_events",
                      sa.Column("observation_count", sa.Integer(), nullable=True))
    if "duration_s" not in have:
        op.add_column("ppe_events", sa.Column("duration_s", sa.Float(), nullable=True))


def downgrade() -> None:
    have = _cols("ppe_events")
    for c in ("duration_s", "observation_count", "updated_at"):
        if c in have:
            op.drop_column("ppe_events", c)
