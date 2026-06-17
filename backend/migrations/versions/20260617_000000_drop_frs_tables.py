"""Drop NVR-owned FRS gallery tables (moved to the FRS scenario microservice)

FRS (face recognition) is now a standalone scenario plugin (scenarios/frs) that
owns its own Postgres, Qdrant face index and photo volume. The legacy NVR-side
gallery tables are removed here.

⚠️  DESTRUCTIVE — RUN ONLY AFTER MIGRATING DATA.
Before applying this migration on a deployment that has real FRS data, run the
plugin's one-shot importer so the gallery + photos + vectors land in the FRS
plugin first:

    docker compose -f docker-compose.yml -f docker-compose.ai.yml run --rm \
        -e NVR_DATABASE_URL=postgresql+psycopg2://<nvr_user>:<pw>@db:5432/<nvr_db> \
        -e NVR_FRS_PHOTO_ROOT=/nvr-data/frs \
        frs python migrate_from_nvr.py

Tables dropped: frs_attendance, frs_photos, frs_persons, frs_groups.

The events table AI columns (person_id, detection_type, confidence, bbox,
track_id, attributes) are GENERIC NVR event fields and are intentionally KEPT.

Revision ID: 20260617_000000
Revises: 20260607_000000
Create Date: 2026-06-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260617_000000"
down_revision: Union[str, None] = "20260607_000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop in FK-dependency order (children first).
    op.drop_index("ix_frs_attendance_day", table_name="frs_attendance")
    op.drop_table("frs_attendance")
    op.drop_index("ix_frs_photos_person", table_name="frs_photos")
    op.drop_table("frs_photos")
    op.drop_index("ix_frs_persons_category", table_name="frs_persons")
    op.drop_index("ix_frs_persons_group", table_name="frs_persons")
    op.drop_table("frs_persons")
    op.drop_table("frs_groups")


def downgrade() -> None:
    # Recreate the legacy tables (empty). Mirrors 20260606_000000 upgrade().
    op.create_table(
        "frs_groups",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("group_type", sa.String(50), nullable=True),
        sa.Column("color_code", sa.String(20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("alert_sound", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "frs_persons",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("group_id", sa.String(), nullable=True),
        sa.Column("category", sa.String(20), nullable=False, server_default="standard"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrollment_status", sa.String(20), nullable=False, server_default="unenrolled"),
        sa.Column("photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enrolled_photo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thumbnail_key", sa.String(500), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["group_id"], ["frs_groups.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
    )
    op.create_index("ix_frs_persons_group", "frs_persons", ["group_id"])
    op.create_index("ix_frs_persons_category", "frs_persons", ["category"])
    op.create_table(
        "frs_photos",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=True),
        sa.Column("thumbnail_key", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("embedding_id", sa.String(100), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("liveness_score", sa.Float(), nullable=True),
        sa.Column("sharpness_score", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["person_id"], ["frs_persons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_frs_photos_person", "frs_photos", ["person_id"])
    op.create_table(
        "frs_attendance",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("person_id", sa.String(), nullable=False),
        sa.Column("camera_id", sa.String(), nullable=True),
        sa.Column("day_key", sa.String(10), nullable=False),
        sa.Column("check_in_at", sa.DateTime(), nullable=True),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        sa.Column("sighting_type", sa.String(20), nullable=True),
        sa.Column("event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["person_id"], ["frs_persons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "day_key", name="uq_person_day"),
    )
    op.create_index("ix_frs_attendance_day", "frs_attendance", ["day_key"])
