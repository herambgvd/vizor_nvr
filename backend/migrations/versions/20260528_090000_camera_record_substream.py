"""add record_substream flag to cameras

Revision ID: 20260528_090000
Revises: 20260528_080000
Create Date: 2026-05-28

Adds a boolean column that lets operators opt in to recording from the
camera's sub-stream instead of the main stream.  Lower resolution (~480p)
but ~80% less storage write rate — useful for non-evidence cameras.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_090000"
down_revision = "20260528_080000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column(
            "record_substream",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "record_substream")
