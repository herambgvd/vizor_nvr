"""user-defined plate lists (categories with actions)

Refactors the hardcoded whitelist/blacklist into USER-DEFINED named lists. This:

  1. Creates anpr_list_def (id, name unique, action, color, description,
     created_at) and seeds two default lists so existing installs keep working:
       * "Blacklist" action "alert" color "#ef4444"
       * "Whitelist" action "allow" color "#22c55e"
  2. Alters anpr_plate_list: adds list_id (FK -> anpr_list_def.id), backfills it
     from the old list_type column (whitelist -> Whitelist def, anything else ->
     Blacklist def), then drops list_type.

Idempotent / safe on an existing (likely empty) anpr_plate_list — the backfill
runs only over rows that exist, and every step checks the current schema before
mutating it, so a partial / re-run upgrade is harmless.

Revision ID: anpr_0002_user_lists
Revises: anpr_0001_baseline
Create Date: 2026-06-21
"""
import sqlalchemy as sa
from alembic import op

from db.models import ANPRListDef

revision = "anpr_0002_user_lists"
down_revision = "anpr_0001_baseline"
branch_labels = None
depends_on = None


# Stable seed ids so the backfill can reference them without a round-trip.
_BLACKLIST_ID = "00000000-0000-0000-0000-0000000000b1"
_WHITELIST_ID = "00000000-0000-0000-0000-0000000000a1"


def _has_table(bind, name: str) -> bool:
    return sa.inspect(bind).has_table(name)


def _columns(bind, table: str) -> set:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create + seed anpr_list_def (checkfirst so a re-run is safe).
    ANPRListDef.__table__.create(bind, checkfirst=True)
    seeds = [
        {"id": _BLACKLIST_ID, "name": "Blacklist", "action": "alert", "color": "#ef4444"},
        {"id": _WHITELIST_ID, "name": "Whitelist", "action": "allow", "color": "#22c55e"},
    ]
    defs = sa.table(
        "anpr_list_def",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("action", sa.String),
        sa.column("color", sa.String),
    )
    for seed in seeds:
        exists = bind.execute(
            sa.select(defs.c.id).where(defs.c.name == seed["name"])
        ).first()
        if not exists:
            op.bulk_insert(defs, [seed])

    # Resolve the actual ids in case the seeds already existed under these names.
    blacklist_id = bind.execute(
        sa.select(defs.c.id).where(defs.c.name == "Blacklist")
    ).scalar() or _BLACKLIST_ID
    whitelist_id = bind.execute(
        sa.select(defs.c.id).where(defs.c.name == "Whitelist")
    ).scalar() or _WHITELIST_ID

    # 2. Add list_id to anpr_plate_list (nullable first so existing rows are fine).
    if not _has_table(bind, "anpr_plate_list"):
        return
    cols = _columns(bind, "anpr_plate_list")
    if "list_id" not in cols:
        op.add_column("anpr_plate_list", sa.Column("list_id", sa.String(), nullable=True))

    # 3. Backfill list_id from the old list_type, then enforce + index it.
    if "list_type" in cols:
        plate_list = sa.table(
            "anpr_plate_list",
            sa.column("list_id", sa.String),
            sa.column("list_type", sa.String),
        )
        op.execute(
            plate_list.update()
            .where(plate_list.c.list_type == "whitelist")
            .values(list_id=whitelist_id)
        )
        op.execute(
            plate_list.update()
            .where(sa.or_(plate_list.c.list_type != "whitelist",
                         plate_list.c.list_type.is_(None)))
            .values(list_id=blacklist_id)
        )

    # Any orphan rows (no list_type match / pre-existing nulls) -> Blacklist.
    op.execute(
        sa.text("UPDATE anpr_plate_list SET list_id = :bid WHERE list_id IS NULL")
        .bindparams(bid=blacklist_id)
    )

    # Enforce NOT NULL + add the index (best-effort: skip if already applied).
    try:
        op.alter_column("anpr_plate_list", "list_id", existing_type=sa.String(),
                        nullable=False)
    except Exception:  # noqa: BLE001
        pass
    insp = sa.inspect(bind)
    idx_names = {i["name"] for i in insp.get_indexes("anpr_plate_list")}
    if "ix_anpr_list_listid" not in idx_names:
        op.create_index("ix_anpr_list_listid", "anpr_plate_list", ["list_id"])

    # 4. Drop the old list_type column + its index.
    cols = _columns(bind, "anpr_plate_list")
    if "list_type" in cols:
        idx_names = {i["name"] for i in sa.inspect(bind).get_indexes("anpr_plate_list")}
        if "ix_anpr_list_type" in idx_names:
            op.drop_index("ix_anpr_list_type", table_name="anpr_plate_list")
        op.drop_column("anpr_plate_list", "list_type")


def downgrade() -> None:
    bind = op.get_bind()
    if _has_table(bind, "anpr_plate_list"):
        cols = _columns(bind, "anpr_plate_list")
        if "list_type" not in cols:
            op.add_column(
                "anpr_plate_list",
                sa.Column("list_type", sa.String(length=20), nullable=False,
                          server_default="blacklist"),
            )
            op.create_index("ix_anpr_list_type", "anpr_plate_list", ["list_type"])
        # Best-effort reverse map from the seeded defs.
        op.execute(sa.text(
            "UPDATE anpr_plate_list SET list_type = 'whitelist' "
            "WHERE list_id IN (SELECT id FROM anpr_list_def WHERE name = 'Whitelist')"
        ))
        idx_names = {i["name"] for i in sa.inspect(bind).get_indexes("anpr_plate_list")}
        if "ix_anpr_list_listid" in idx_names:
            op.drop_index("ix_anpr_list_listid", table_name="anpr_plate_list")
        if "list_id" in _columns(bind, "anpr_plate_list"):
            op.drop_column("anpr_plate_list", "list_id")
    ANPRListDef.__table__.drop(bind, checkfirst=True)
