"""public dashboard + third-party ingest columns on ppe_settings

Adds the four SDK SettingsStore columns to the singleton ppe_settings row:
  * public_dashboard_enabled (Boolean, default False)
  * ingest_api_enabled       (Boolean, default False)
  * ingest_api_key           (String(128), nullable)
  * public_show_names        (Boolean, default False)

Idempotent: each column is added only if absent (inspect before adding), so a
re-run or a DB that already has them is harmless.

Revision ID: ppe_0002_public_ingest
Revises: ppe_0001_baseline
Create Date: 2026-06-21
"""
import sqlalchemy as sa
from alembic import op

revision = "ppe_0002_public_ingest"
down_revision = "ppe_0001_baseline"
branch_labels = None
depends_on = None

_TABLE = "ppe_settings"
_COLUMNS = (
    ("public_dashboard_enabled", sa.Column("public_dashboard_enabled", sa.Boolean(),
                                            nullable=False, server_default=sa.false())),
    ("ingest_api_enabled", sa.Column("ingest_api_enabled", sa.Boolean(),
                                     nullable=False, server_default=sa.false())),
    ("ingest_api_key", sa.Column("ingest_api_key", sa.String(length=128), nullable=True)),
    ("public_show_names", sa.Column("public_show_names", sa.Boolean(),
                                    nullable=False, server_default=sa.false())),
)


def _columns(bind) -> set:
    return {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    have = _columns(bind)
    for name, col in _COLUMNS:
        if name not in have:
            op.add_column(_TABLE, col)


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    have = _columns(bind)
    for name, _ in reversed(_COLUMNS):
        if name in have:
            op.drop_column(_TABLE, name)
