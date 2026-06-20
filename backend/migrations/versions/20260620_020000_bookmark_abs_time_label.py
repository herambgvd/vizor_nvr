"""add abs_time, label, category to bookmarks

Revision ID: 20260620_020000
Revises: 20260620_010000
Create Date: 2026-06-20

Adds an absolute seek anchor (abs_time, Unix epoch seconds) plus optional
label/category to bookmarks. abs_time is what playback seeks to directly — the
older `timestamp` column is a recording-relative display offset that on its own
cannot locate a moment. Legacy rows keep abs_time NULL (they fall back to the
recording-relative offset for display only).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260620_020000"
down_revision = "20260620_010000"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = {c["name"] for c in insp.get_columns(table)}
    except Exception:
        return False
    return column in cols


def upgrade() -> None:
    if not _has_column("bookmarks", "abs_time"):
        op.add_column("bookmarks", sa.Column("abs_time", sa.Float(), nullable=True))
    if not _has_column("bookmarks", "label"):
        op.add_column("bookmarks", sa.Column("label", sa.String(length=120), nullable=True))
    if not _has_column("bookmarks", "category"):
        op.add_column("bookmarks", sa.Column("category", sa.String(length=40), nullable=True))


def downgrade() -> None:
    if _has_column("bookmarks", "category"):
        op.drop_column("bookmarks", "category")
    if _has_column("bookmarks", "label"):
        op.drop_column("bookmarks", "label")
    if _has_column("bookmarks", "abs_time"):
        op.drop_column("bookmarks", "abs_time")
