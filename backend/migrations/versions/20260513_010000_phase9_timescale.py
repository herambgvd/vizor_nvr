"""
Phase 9 — TimescaleDB extension + events hypertable + continuous aggregates

Converts the `events` table into a TimescaleDB hypertable partitioned by
`triggered_at`. Adds compression, retention, and continuous aggregates
sized for dashboard queries.

This migration is Postgres-only (TimescaleDB extension does not exist on
SQLite). Detection: if the database is SQLite, the migration becomes a
no-op so existing unit tests keep passing.

Revision ID: phase9_timescale
Revises: phase8_ai_foundations
Create Date: 2026-05-13

Notes:
  - Hypertable on `events.triggered_at`, 7-day chunks (default sizing)
  - Compress chunks older than 7 days (drops ~85% storage)
  - Drop chunks older than 90 days (retention)
  - Continuous aggregates: 5min, 1h, 1d buckets per (camera_id,
    detection_type, severity)
  - Aggregates refresh policies run hourly with 30-min lookback
"""

from alembic import op
import sqlalchemy as sa


revision = "phase9_timescale"
down_revision = "phase8_ai_foundations"
branch_labels = None
depends_on = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        # SQLite (test) — nothing to do; events table works as plain table
        return

    bind = op.get_bind()

    # ── Extension ────────────────────────────────────────────────────────
    bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS timescaledb"))

    # ── Prepare events table for hypertable conversion ──────────────────
    # TimescaleDB requires the partitioning column (`triggered_at`) to be
    # part of every unique index, including the primary key. The existing
    # PK is on (id) only — we drop it and recreate as (id, triggered_at).
    # The dedup_key unique index also has to be widened.
    bind.execute(sa.text("ALTER TABLE events DROP CONSTRAINT IF EXISTS events_pkey CASCADE"))
    bind.execute(sa.text(
        "ALTER TABLE events ADD CONSTRAINT events_pkey "
        "PRIMARY KEY (id, triggered_at)"
    ))

    bind.execute(sa.text("DROP INDEX IF EXISTS ix_events_dedup_key"))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX ix_events_dedup_key "
        "ON events (dedup_key, triggered_at)"
    ))

    # ── Hypertable ───────────────────────────────────────────────────────
    # 7-day chunk interval is the right shape for our event volumes.
    bind.execute(sa.text(
        "SELECT create_hypertable('events', 'triggered_at', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    ))

    # ── Compression policy ───────────────────────────────────────────────
    bind.execute(sa.text(
        "ALTER TABLE events SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'camera_id, detection_type', "
        "timescaledb.compress_orderby = 'triggered_at DESC'"
        ")"
    ))
    bind.execute(sa.text(
        "SELECT add_compression_policy('events', INTERVAL '7 days', "
        "if_not_exists => TRUE)"
    ))

    # ── Retention policy ─────────────────────────────────────────────────
    bind.execute(sa.text(
        "SELECT add_retention_policy('events', INTERVAL '90 days', "
        "if_not_exists => TRUE)"
    ))

    # ── Continuous aggregates ────────────────────────────────────────────
    # 5-minute buckets — drives the timeline marker density layer
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS events_5min
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('5 minutes', triggered_at) AS bucket,
            camera_id,
            detection_type,
            severity,
            count(*)::int AS event_count,
            avg(confidence)::real AS avg_confidence
        FROM events
        GROUP BY bucket, camera_id, detection_type, severity
        WITH NO DATA
    """))

    # 1-hour buckets — drives hourly dashboards
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS events_1h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 hour', triggered_at) AS bucket,
            camera_id,
            detection_type,
            severity,
            count(*)::int AS event_count,
            avg(confidence)::real AS avg_confidence
        FROM events
        GROUP BY bucket, camera_id, detection_type, severity
        WITH NO DATA
    """))

    # 1-day buckets — drives 30-day trend charts + monthly reports
    bind.execute(sa.text("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS events_1d
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', triggered_at) AS bucket,
            camera_id,
            detection_type,
            severity,
            count(*)::int AS event_count,
            avg(confidence)::real AS avg_confidence
        FROM events
        GROUP BY bucket, camera_id, detection_type, severity
        WITH NO DATA
    """))

    # ── Refresh policies ────────────────────────────────────────────────
    # 5-min view refreshes every 5 minutes with 30-min lookback
    bind.execute(sa.text(
        "SELECT add_continuous_aggregate_policy('events_5min', "
        "start_offset => INTERVAL '30 minutes', "
        "end_offset => INTERVAL '5 minutes', "
        "schedule_interval => INTERVAL '5 minutes', "
        "if_not_exists => TRUE)"
    ))
    bind.execute(sa.text(
        "SELECT add_continuous_aggregate_policy('events_1h', "
        "start_offset => INTERVAL '3 hours', "
        "end_offset => INTERVAL '1 hour', "
        "schedule_interval => INTERVAL '30 minutes', "
        "if_not_exists => TRUE)"
    ))
    bind.execute(sa.text(
        "SELECT add_continuous_aggregate_policy('events_1d', "
        "start_offset => INTERVAL '3 days', "
        "end_offset => INTERVAL '1 day', "
        "schedule_interval => INTERVAL '6 hours', "
        "if_not_exists => TRUE)"
    ))


def downgrade() -> None:
    if not _is_postgres():
        return

    bind = op.get_bind()

    # Continuous aggregates must be dropped before hypertable conversion
    # is reversed. Reverse order from upgrade.
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS events_1d CASCADE"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS events_1h CASCADE"))
    bind.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS events_5min CASCADE"))

    # Drop policies (idempotent)
    try:
        bind.execute(sa.text("SELECT remove_retention_policy('events', if_exists => TRUE)"))
    except Exception:
        pass
    try:
        bind.execute(sa.text("SELECT remove_compression_policy('events', if_exists => TRUE)"))
    except Exception:
        pass

    # TimescaleDB does not support converting a hypertable back to a
    # regular table without data loss. Documenting the workaround:
    #   1. Create regular_events as plain table with same schema
    #   2. INSERT INTO regular_events SELECT * FROM events
    #   3. DROP TABLE events
    #   4. ALTER TABLE regular_events RENAME TO events
    # Not automated here because downgrade is rare and risky.
