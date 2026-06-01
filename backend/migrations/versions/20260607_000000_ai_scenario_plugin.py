"""AI scenario plugin platform (Phase 1) — manifest/registry columns.

Adds self-describing-plugin metadata to ai_scenarios so scenarios can be
registered from a manifest (scenario.json) instead of a hardcoded catalog.

Revision ID: 20260607_000000
Revises: 20260606_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260607_000000"
down_revision = "20260606_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_scenarios", sa.Column("version", sa.String(30), nullable=True))
    op.add_column("ai_scenarios", sa.Column("capabilities", sa.JSON(), nullable=True))
    op.add_column("ai_scenarios", sa.Column("license_feature", sa.String(50), nullable=True))
    op.add_column("ai_scenarios", sa.Column("manifest", sa.JSON(), nullable=True))
    op.add_column("ai_scenarios", sa.Column(
        "source", sa.String(20), nullable=False, server_default="builtin"))
    op.add_column("ai_scenarios", sa.Column(
        "registered", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("ai_scenarios", sa.Column("registered_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in ("registered_at", "registered", "source", "manifest",
                "license_feature", "capabilities", "version"):
        op.drop_column("ai_scenarios", col)
