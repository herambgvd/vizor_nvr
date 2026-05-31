"""merge all 20260528 branch heads into a single head

Revision ID: 20260529_000000
Revises: 20260528_010000, 20260528_030000, 20260528_040000, 20260528_050000
Create Date: 2026-05-29

Merges the four independent branch tips into a single head so that
`alembic upgrade head` (singular) works from the docker-compose command.

Branch topology:
  20260527_010000 (base)
    ├─ 20260528_010000  (ptz_tour)
    ├─ 20260528_020000  (retention) → 20260528_030000 (schedule_templates)
    ├─ 20260528_040000  (snapshot_config)
    └─ 20260528_050000  (bandwidth_alert_threshold_pct)

Note: 20260528_020000 is intentionally not listed here because
      20260528_030000 is already its child (downstream). Including
      020000 would cause an overlap error.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260529_000000"
down_revision = (
    # 20260528_010000 removed: it is an ANCESTOR of 20260528_030000
    # (010000 → 020000 → 030000), so listing both made alembic consume
    # 010000 twice → KeyError during merge. 030000 already includes it.
    "20260528_030000",
    "20260528_040000",
    "20260528_050000",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
