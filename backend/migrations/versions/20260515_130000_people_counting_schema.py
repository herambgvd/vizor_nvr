"""
People Counting — zones + counts hypertable + attendance.punches

Creates:
  - people_count_zones: per-camera zones (line for in/out, polygon for crowd)
  - people_counts: minute-bucketed in/out/occupancy hypertable
  - frs_attendance.punches: JSON array of in/out punches per day

Revision ID: people_counting_schema
Revises: ai_scenarios_schema_meta
"""
from alembic import op
import sqlalchemy as sa


revision = "people_counting_schema"
down_revision = "ai_scenarios_schema_meta"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


def upgrade():
    # ── people_count_zones ──────────────────────────────────────────────
    op.create_table(
        "people_count_zones",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "camera_id",
            sa.String(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("scenario", sa.String(20), nullable=False),  # in_out | crowd
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=True),
        sa.Column("direction_a_label", sa.String(20), nullable=False, server_default="in"),
        sa.Column("direction_b_label", sa.String(20), nullable=False, server_default="out"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_people_count_zones_camera_scenario",
        "people_count_zones",
        ["camera_id", "scenario"],
    )

    # ── people_counts ───────────────────────────────────────────────────
    # Minute-bucketed aggregations. Hypertable on bucket_ts for fast
    # range queries + retention.
    op.create_table(
        "people_counts",
        sa.Column("bucket_ts", sa.DateTime(), nullable=False),
        sa.Column(
            "camera_id",
            sa.String(),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "zone_id",
            sa.String(),
            sa.ForeignKey("people_count_zones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("in_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("out_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("occupancy", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crowd_alerts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_people_counts_zone_bucket",
        "people_counts",
        ["zone_id", "bucket_ts"],
    )
    op.create_index(
        "ix_people_counts_camera_bucket",
        "people_counts",
        ["camera_id", "bucket_ts"],
    )

    # ── frs_attendance.punches ──────────────────────────────────────────
    op.add_column(
        "frs_attendance",
        sa.Column("punches", sa.JSON(), nullable=True),
    )

    # ── Convert people_counts to hypertable ─────────────────────────────
    if _is_postgres():
        bind = op.get_bind()
        bind.execute(sa.text(
            "ALTER TABLE people_counts ADD CONSTRAINT people_counts_pkey "
            "PRIMARY KEY (zone_id, bucket_ts)"
        ))
        bind.execute(sa.text(
            "SELECT create_hypertable('people_counts', 'bucket_ts', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        ))


def downgrade():
    op.drop_column("frs_attendance", "punches")
    op.drop_index("ix_people_counts_camera_bucket", table_name="people_counts")
    op.drop_index("ix_people_counts_zone_bucket", table_name="people_counts")
    op.drop_table("people_counts")
    op.drop_index("ix_people_count_zones_camera_scenario", table_name="people_count_zones")
    op.drop_table("people_count_zones")
