"""Fix roles table — add missing columns

Revision ID: 003_fix_roles_schema
Revises: 002_phase1_features
Create Date: 2026-03-06

The initial migration created the roles table without description, is_system,
and updated_at columns that the ORM model requires.  This migration adds them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_fix_roles_schema"
down_revision: Union[str, None] = "002_phase1_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use batch_alter_table for SQLite compatibility — SQLite doesn't support
    # bare ALTER COLUMN TYPE statements, so Alembic must rebuild the table.
    with op.batch_alter_table("roles") as batch:
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(sa.Column(
            "is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column(
            "updated_at", sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True))
        batch.alter_column(
            "name",
            existing_type=sa.String(length=50),
            type_=sa.String(length=30),
            existing_nullable=False,
        )
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_roles_name"), table_name="roles")
    with op.batch_alter_table("roles") as batch:
        batch.alter_column(
            "name",
            existing_type=sa.String(length=30),
            type_=sa.String(length=50),
            existing_nullable=False,
        )
        batch.drop_column("updated_at")
        batch.drop_column("is_system")
        batch.drop_column("description")
