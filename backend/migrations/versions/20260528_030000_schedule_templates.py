"""add schedule_templates table

Revision ID: 20260528_030000
Revises: 20260528_020000
Create Date: 2026-05-28

Creates a schedule_templates table for saving and bulk-applying
recording schedule configurations.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260528_030000"
down_revision = "20260528_020000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "schedule_templates" not in existing_tables:
        op.create_table(
            "schedule_templates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(100), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("grid", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())
    if "schedule_templates" in existing_tables:
        op.drop_table("schedule_templates")
