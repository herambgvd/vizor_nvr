"""Add backup_schedules table

Revision ID: 20260605_030000
Revises: 20260605_020000
Create Date: 2026-06-05 03:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260605_030000'
down_revision: Union[str, None] = '20260605_020000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'backup_schedules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('source_pool_id', sa.String(), nullable=False),
        sa.Column('target_pool_id', sa.String(), nullable=False),
        sa.Column('schedule', sa.String(100), nullable=False, server_default='0 2 * * *'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('age_days', sa.Integer(), nullable=False, server_default='7'),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_status', sa.String(20), nullable=True),
        sa.Column('last_run_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.add_column('storage_pools', sa.Column('raid_level', sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_table('backup_schedules')
    op.drop_column('storage_pools', 'raid_level')
