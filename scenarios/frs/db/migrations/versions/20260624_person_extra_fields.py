"""Extended person profile fields (ID document, department, validity, etc.)

Adds operator-entered profile columns to frs_persons:
department, designation, contact_number, date_of_joining, id_type, id_number,
id_file_key, validity_start, validity_end, auto_remove — plus an index on
(auto_remove, validity_end) for the validity-expiry sweeper. All nullable, so the
migration is safe on an existing gallery.

Revision ID: 20260624_person_extra_fields
Revises: 20260620_frs_settings
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "20260624_person_extra_fields"
down_revision = "20260620_frs_settings"
branch_labels = None
depends_on = None


_COLUMNS = [
    ("department", sa.String(120)),
    ("designation", sa.String(120)),
    ("contact_number", sa.String(40)),
    ("date_of_joining", sa.Date()),
    ("id_type", sa.String(60)),
    ("id_number", sa.String(120)),
    ("id_file_key", sa.String(500)),
    ("validity_start", sa.Date()),
    ("validity_end", sa.Date()),
]


def _existing_columns(bind) -> set:
    insp = sa.inspect(bind)
    return {c["name"] for c in insp.get_columns("frs_persons")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _existing_columns(bind)
    for name, col_type in _COLUMNS:
        if name not in have:
            op.add_column("frs_persons", sa.Column(name, col_type, nullable=True))
    if "auto_remove" not in have:
        op.add_column(
            "frs_persons",
            sa.Column("auto_remove", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    insp = sa.inspect(bind)
    idx = {i["name"] for i in insp.get_indexes("frs_persons")}
    if "ix_frs_persons_validity" not in idx:
        op.create_index("ix_frs_persons_validity", "frs_persons",
                        ["auto_remove", "validity_end"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    idx = {i["name"] for i in insp.get_indexes("frs_persons")}
    if "ix_frs_persons_validity" in idx:
        op.drop_index("ix_frs_persons_validity", table_name="frs_persons")
    have = _existing_columns(bind)
    for name, _ in [("auto_remove", None), *[(c[0], None) for c in _COLUMNS]]:
        if name in have:
            op.drop_column("frs_persons", name)
