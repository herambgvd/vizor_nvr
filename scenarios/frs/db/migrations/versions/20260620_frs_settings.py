"""frs_settings table (public dashboard + ingest API toggles)

Adds the singleton FRS feature-config table. Idempotent (checkfirst) so it is
safe on any existing DB.

Revision ID: 20260620_frs_settings
Revises: 1ddf1568b949
Create Date: 2026-06-20
"""
from alembic import op

from db.models import Base, FRSSettings

revision = "20260620_frs_settings"
down_revision = "1ddf1568b949"
branch_labels = None
depends_on = None


def upgrade() -> None:
    FRSSettings.__table__.create(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    FRSSettings.__table__.drop(op.get_bind(), checkfirst=True)
