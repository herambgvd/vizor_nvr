"""
PeopleCountZone.severity column.

Revision ID: zone_severity
Revises: frs_photo_status
"""
from alembic import op
import sqlalchemy as sa


revision = "zone_severity"
down_revision = "frs_photo_status"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "people_count_zones",
        sa.Column(
            "severity",
            sa.String(20),
            nullable=False,
            server_default="info",
        ),
    )


def downgrade():
    op.drop_column("people_count_zones", "severity")
