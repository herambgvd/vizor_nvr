"""Add spot_outputs table

Revision ID: 20260605_050000
Revises: 20260605_040000
Create Date: 2026-06-05 05:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260605_050000'
down_revision: Union[str, None] = '20260605_040000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'spot_outputs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('layout', sa.String(20), nullable=False, server_default='2x2'),
        sa.Column('camera_ids', sa.JSON(), nullable=True),
        sa.Column('quality', sa.String(10), nullable=False, server_default='medium'),
        sa.Column('stream_name', sa.String(100), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stream_name'),
    )


def downgrade() -> None:
    op.drop_table('spot_outputs')
