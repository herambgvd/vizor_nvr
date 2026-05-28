"""Add cluster_nodes table

Revision ID: 20260605_040000
Revises: 20260605_030000
Create Date: 2026-06-05 04:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260605_040000'
down_revision: Union[str, None] = '20260605_030000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cluster_nodes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('node_id', sa.String(100), nullable=False),
        sa.Column('hostname', sa.String(200), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='standby'),
        sa.Column('is_leader', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('last_heartbeat_at', sa.DateTime(), nullable=True),
        sa.Column('heartbeat_interval_sec', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('lease_ttl_sec', sa.Integer(), nullable=False, server_default='15'),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('version', sa.String(20), nullable=True),
        sa.Column('promoted_at', sa.DateTime(), nullable=True),
        sa.Column('demoted_at', sa.DateTime(), nullable=True),
        sa.Column('failover_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('node_id'),
    )


def downgrade() -> None:
    op.drop_table('cluster_nodes')
