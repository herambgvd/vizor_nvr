"""Initial migration - all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-05

This is the initial migration representing the existing database schema.
Run `alembic stamp head` on existing databases to mark them as migrated.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Roles ───────────────────────────────────────────────────────────
    op.create_table('roles',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('permissions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # ── Users ───────────────────────────────────────────────────────────
    op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=200), nullable=True),
        sa.Column('hashed_password', sa.String(length=255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('role_id', sa.String(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=False)

    # ── Storage Pools ───────────────────────────────────────────────────
    op.create_table('storage_pools',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('path', sa.String(length=500), nullable=False),
        sa.Column('pool_type', sa.String(length=20), nullable=True),
        sa.Column('max_size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('mount_options', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('path')
    )

    # ── Camera Groups ───────────────────────────────────────────────────
    op.create_table('camera_groups',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('color', sa.String(length=7), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # ── Cameras ─────────────────────────────────────────────────────────
    op.create_table('cameras',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('main_stream_url', sa.String(length=500), nullable=False),
        sa.Column('sub_stream_url', sa.String(length=500), nullable=True),
        sa.Column('detect_stream_url', sa.String(length=500), nullable=True),
        sa.Column('onvif_host', sa.String(length=200), nullable=True),
        sa.Column('onvif_port', sa.Integer(), nullable=True),
        sa.Column('onvif_username', sa.String(length=100), nullable=True),
        sa.Column('onvif_password', sa.String(length=100), nullable=True),
        sa.Column('ptz_capable', sa.Boolean(), nullable=True),
        sa.Column('ptz_presets', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('is_recording', sa.Boolean(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.Column('max_retries', sa.Integer(), nullable=True),
        sa.Column('last_retry_at', sa.DateTime(), nullable=True),
        sa.Column('last_online_at', sa.DateTime(), nullable=True),
        sa.Column('resolution', sa.String(length=20), nullable=True),
        sa.Column('fps', sa.Integer(), nullable=True),
        sa.Column('bitrate', sa.String(length=20), nullable=True),
        sa.Column('sub_resolution', sa.String(length=20), nullable=True),
        sa.Column('sub_fps', sa.Integer(), nullable=True),
        sa.Column('codec', sa.String(length=20), nullable=True),
        sa.Column('recording_fps', sa.Integer(), nullable=True),
        sa.Column('recording_schedule', sa.JSON(), nullable=True),
        sa.Column('storage_pool_id', sa.String(), nullable=True),
        sa.Column('bandwidth_limit_kbps', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('thumbnail_path', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['storage_pool_id'], ['storage_pools.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Camera-Group Association ────────────────────────────────────────
    op.create_table('camera_group_members',
        sa.Column('camera_id', sa.String(), nullable=False),
        sa.Column('group_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['camera_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('camera_id', 'group_id')
    )

    # ── User-CameraGroup Access ────────────────────────────────────────
    op.create_table('user_camera_groups',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('group_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['camera_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'group_id')
    )

    # ── Recordings ──────────────────────────────────────────────────────
    op.create_table('recordings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('camera_id', sa.String(), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('start_time', sa.DateTime(), nullable=False),
        sa.Column('end_time', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('resolution', sa.String(length=20), nullable=True),
        sa.Column('fps', sa.Integer(), nullable=True),
        sa.Column('codec', sa.String(length=20), nullable=True),
        sa.Column('stream_type', sa.String(length=20), nullable=True),
        sa.Column('storage_pool_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.ForeignKeyConstraint(['camera_id'], ['cameras.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['storage_pool_id'], ['storage_pools.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_recordings_camera_id'), 'recordings', ['camera_id'], unique=False)
    op.create_index(op.f('ix_recordings_start_time'), 'recordings', ['start_time'], unique=False)

    # ── Storage Tier Rules ──────────────────────────────────────────────
    op.create_table('storage_tier_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('source_pool_id', sa.String(), nullable=False),
        sa.Column('target_pool_id', sa.String(), nullable=False),
        sa.Column('age_threshold_hours', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Cloud Storage Configs ───────────────────────────────────────────
    op.create_table('cloud_storage_configs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=20), nullable=True),
        sa.Column('endpoint', sa.String(length=500), nullable=True),
        sa.Column('bucket', sa.String(length=200), nullable=False),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('access_key', sa.String(length=200), nullable=True),
        sa.Column('secret_key', sa.String(length=500), nullable=True),
        sa.Column('prefix', sa.String(length=200), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('sync_enabled', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # ── Settings ────────────────────────────────────────────────────────
    op.create_table('settings',
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('is_sensitive', sa.Boolean(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_settings_category'), 'settings', ['category'], unique=False)

    # ── Audit Logs ──────────────────────────────────────────────────────
    op.create_table('audit_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('resource_type', sa.String(length=50), nullable=True),
        sa.Column('resource_id', sa.String(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_settings_category'), table_name='settings')
    op.drop_table('settings')
    op.drop_table('cloud_storage_configs')
    op.drop_table('storage_tier_rules')
    op.drop_index(op.f('ix_recordings_start_time'), table_name='recordings')
    op.drop_index(op.f('ix_recordings_camera_id'), table_name='recordings')
    op.drop_table('recordings')
    op.drop_table('user_camera_groups')
    op.drop_table('camera_group_members')
    op.drop_table('cameras')
    op.drop_table('camera_groups')
    op.drop_table('storage_pools')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
