"""remove AI tables, aggregates, and AI-only event columns

Revision ID: 20260527_000000
Revises: zone_severity
Create Date: 2026-05-27

Drops:
  * TimescaleDB continuous aggregate views events_5min / events_1h / events_1d
    (depend on detection_type / confidence)
  * AI-only columns on the events table
  * All AI feature tables

Down-revision recreates the AI tables as empty single-PK shells so test
rollback works; the continuous aggregates and event columns are NOT
re-created on downgrade (data is not preserved across the purge).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260527_000000"
down_revision = "zone_severity"
branch_labels = None
depends_on = None


AI_TABLES = [
    # Drop children before parents.
    "frs_attendance",
    "frs_photos",
    "frs_investigations",
    "frs_persons",
    "frs_groups",
    "people_counts",
    "people_count_zones",
    "vq_captions",
    "vq_attributes",
    "inference_jobs",
    "model_deployments",
    "models",
    "webhook_deliveries",
    "webhook_subscriptions",
    "metropolis_services",
    "camera_ai_configs",
    "ai_scenarios",
]

CONTINUOUS_AGGREGATES = ["events_5min", "events_1h", "events_1d"]

# AI-only columns on the events table.
EVENT_AI_COLUMNS = [
    "detection_type",
    "confidence",
    "bbox",
    "track_id",
    "person_id",
    "attributes",
]


def _is_timescale(bind) -> bool:
    """Best-effort check: TimescaleDB extension is loaded."""
    try:
        row = bind.execute(
            sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        ).first()
        return row is not None
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1) Continuous aggregates — only meaningful under Timescale/Postgres.
    if dialect == "postgresql" and _is_timescale(bind):
        for view in CONTINUOUS_AGGREGATES:
            op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE")
    else:
        # SQLite / non-Timescale: views (if they exist as plain views) get dropped too.
        for view in CONTINUOUS_AGGREGATES:
            op.execute(f"DROP VIEW IF EXISTS {view}")

    # 2) AI columns on events.
    inspector = sa.inspect(bind)
    if "events" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("events")}
        cols_to_drop = [c for c in EVENT_AI_COLUMNS if c in existing_cols]
        if cols_to_drop:
            # Drop indexes that reference AI columns first; batch_alter_table
            # recreates the table and would fail trying to rebuild them.
            existing_indexes = {idx["name"] for idx in inspector.get_indexes("events")}
            ai_indexes = [
                "ix_events_detection_type",
                "ix_events_track_id",
                "ix_events_person_id",
            ]
            for idx_name in ai_indexes:
                if idx_name in existing_indexes:
                    op.drop_index(idx_name, table_name="events")

            # Reflect the actual live table so batch_alter_table uses real DB
            # schema, not stale ORM metadata (AI columns were already stripped
            # from ORM but may still exist in the DB with associated indexes).
            live_table = sa.Table("events", sa.MetaData(), autoload_with=bind)
            with op.batch_alter_table("events", copy_from=live_table) as batch:
                for col in cols_to_drop:
                    batch.drop_column(col)

    # 3) AI tables.
    inspector = sa.inspect(bind)  # refresh
    existing_tables = set(inspector.get_table_names())
    for table in AI_TABLES:
        if table in existing_tables:
            op.drop_table(table)


def downgrade() -> None:
    """Recreate AI tables as empty shells. Aggregates and columns NOT restored."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    for table in reversed(AI_TABLES):
        if table not in existing:
            op.create_table(
                table,
                sa.Column("id", sa.Integer, primary_key=True),
            )
