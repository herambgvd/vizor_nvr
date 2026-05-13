"""Cross-cutting X.3 — composite indexes for hot query paths

Revision ID: 010_perf_composite_indexes
Revises: 009_phase5_notifications
Create Date: 2026-03-12 00:00:00

Replaces single-column indexes on (camera_id, start_time)-style filters with
covering composite indexes so the planner can do an index-only range scan
instead of a single-col seek + filter. Drops the now-redundant single-column
indexes to keep write amplification bounded.

Hot queries this targets:
  - recordings list per camera within a date range  (camera_id, start_time)
  - timeline / playback range scans                 (camera_id, start_time)
  - events feed per camera                          (camera_id, triggered_at)
  - audit log per camera / per user                 (camera_id|user_id, created_at)
"""
from alembic import op


revision = "010_perf_composite_indexes"
down_revision = "009_phase5_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── recordings: (camera_id, start_time DESC) — most queries are
    #    "latest segments for this camera" or "range within a day".
    op.create_index(
        "ix_recordings_camera_start_time",
        "recordings",
        ["camera_id", "start_time"],
        unique=False,
    )
    # Drop the single-col indexes that the composite now covers.
    # ix_recordings_camera_id is redundant — composite leads with camera_id.
    # ix_recordings_start_time is kept (some retention/global queries filter
    # by start_time alone without a camera_id predicate).
    op.drop_index("ix_recordings_camera_id", table_name="recordings")

    # ── events: (camera_id, triggered_at DESC) for per-camera event feeds.
    op.create_index(
        "ix_events_camera_triggered_at",
        "events",
        ["camera_id", "triggered_at"],
        unique=False,
    )
    op.drop_index("ix_events_camera_id", table_name="events")

    # ── audit_logs: two composites for the two dominant filters.
    op.create_index(
        "ix_audit_logs_user_created_at",
        "audit_logs",
        ["user_id", "created_at"],
        unique=False,
    )
    # Existing single-col ix_audit_logs_user_id is subsumed by the composite.
    op.drop_index("ix_audit_logs_user_id", table_name="audit_logs")


def downgrade() -> None:
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"], unique=False)
    op.drop_index("ix_audit_logs_user_created_at", table_name="audit_logs")

    op.create_index("ix_events_camera_id", "events", ["camera_id"], unique=False)
    op.drop_index("ix_events_camera_triggered_at", table_name="events")

    op.create_index("ix_recordings_camera_id", "recordings", ["camera_id"], unique=False)
    op.drop_index("ix_recordings_camera_start_time", table_name="recordings")
