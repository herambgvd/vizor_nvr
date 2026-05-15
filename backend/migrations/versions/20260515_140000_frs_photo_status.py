"""
FRSPhoto enrollment status fields.

Revision ID: frs_photo_status
Revises: people_counting_schema
"""
from alembic import op
import sqlalchemy as sa


revision = "frs_photo_status"
down_revision = "people_counting_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "frs_photos",
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "frs_photos",
        sa.Column("error_code", sa.String(50), nullable=True),
    )
    op.add_column(
        "frs_photos",
        sa.Column("error", sa.Text(), nullable=True),
    )
    # Drop unique on qdrant_point_id — placeholders during enrollment
    # otherwise collide. Keep the regular index for lookup speed.
    try:
        op.drop_index("ix_frs_photos_qdrant_point_id", table_name="frs_photos")
    except Exception:
        pass
    op.create_index(
        "ix_frs_photos_qdrant_point_id",
        "frs_photos",
        ["qdrant_point_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_frs_photos_qdrant_point_id", table_name="frs_photos")
    op.create_index(
        "ix_frs_photos_qdrant_point_id",
        "frs_photos",
        ["qdrant_point_id"],
        unique=True,
    )
    op.drop_column("frs_photos", "error")
    op.drop_column("frs_photos", "error_code")
    op.drop_column("frs_photos", "status")
