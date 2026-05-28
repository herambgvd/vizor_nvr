"""Add backchannel_capable column to cameras

Revision ID: 20260528_070000
Revises: 20260529_000000
Create Date: 2026-05-28 07:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '20260528_070000'
down_revision = '20260529_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility
    with op.batch_alter_table('cameras', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('backchannel_capable', sa.Boolean(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table('cameras', schema=None) as batch_op:
        batch_op.drop_column('backchannel_capable')
