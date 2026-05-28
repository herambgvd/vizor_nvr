"""merge credentials_status and backchannel_capable branches

Revision ID: 20260528_080000
Revises: 20260528_060000, 20260528_070000
Create Date: 2026-05-28

Merges the two parallel branches that both extend 20260529_000000:
  20260528_060000 (credentials_status)
  20260528_070000 (backchannel_capable)
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_080000"
down_revision = ("20260528_060000", "20260528_070000")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
