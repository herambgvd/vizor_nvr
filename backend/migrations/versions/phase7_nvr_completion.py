"""
Phase 7 — NVR Completion Features

Revision ID: phase7_nvr_completion
Revises: phase6_access_control
Create Date: 2026-05-12

Adds:
  - cameras.pre_buffer_seconds
  - cameras.post_buffer_seconds
  - recordings.has_motion
  - recordings.event_marker (JSON for timeline markers)
  - camera_health_snapshots table
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'phase7_nvr_completion'
down_revision = '014_phase6_access_control'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── cameras ───────────────────────────────────────────────────────
    op.add_column(
        'cameras',
        sa.Column('pre_buffer_seconds', sa.Integer(), nullable=True, server_default='10')
    )
    op.add_column(
        'cameras',
        sa.Column('post_buffer_seconds', sa.Integer(), nullable=True, server_default='30')
    )

    # ── recordings ────────────────────────────────────────────────────
    op.add_column(
        'recordings',
        sa.Column('has_motion', sa.Boolean(), nullable=True, server_default='0')
    )
    op.add_column(
        'recordings',
        sa.Column('event_markers', sa.JSON(), nullable=True)
    )
    op.create_index('ix_recordings_has_motion', 'recordings', ['has_motion'])

    # ── camera health snapshots ───────────────────────────────────────
    op.create_table(
        'camera_health_snapshots',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('camera_id', sa.String(), nullable=False, index=True),
        sa.Column('packet_loss_percent', sa.Float(), nullable=True),
        sa.Column('bitrate_kbps', sa.Integer(), nullable=True),
        sa.Column('fps_actual', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(20), nullable=True),
        sa.Column('captured_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_health_camera_time', 'camera_health_snapshots', ['camera_id', 'captured_at'])


def downgrade() -> None:
    op.drop_column('cameras', 'pre_buffer_seconds')
    op.drop_column('cameras', 'post_buffer_seconds')

    op.drop_index('ix_recordings_has_motion', table_name='recordings')
    op.drop_column('recordings', 'has_motion')
    op.drop_column('recordings', 'event_markers')

    op.drop_index('ix_health_camera_time', table_name='camera_health_snapshots')
    op.drop_table('camera_health_snapshots')
