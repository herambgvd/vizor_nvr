"""Phase 1 features — recording lock columns

Revision ID: 002_phase1_features
Revises: 001_initial
Create Date: 2026-03-06

Adds:
  - recordings.locked (Boolean, default False)
  - recordings.locked_by (String, nullable)
  - recordings.locked_at (DateTime, nullable)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_phase1_features"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Recording lock / protect ─────────────────────────────────────────

    op.add_column(
        "recordings",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "recordings",
        sa.Column("locked_by", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "recordings",
        sa.Column("locked_at", sa.DateTime(), nullable=True),
    )

    # Index to quickly find/skip locked recordings in retention queries
    op.create_index(
        "ix_recordings_locked",
        "recordings",
        ["locked"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_recordings_locked", table_name="recordings")
    op.drop_column("recordings", "locked_at")
    op.drop_column("recordings", "locked_by")
    op.drop_column("recordings", "locked", )
