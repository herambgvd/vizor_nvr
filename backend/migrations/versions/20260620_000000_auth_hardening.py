"""Auth hardening — TOTP replay protection + login brute-force lockout

Adds:
  users.totp_last_step        — RFC 6238 §5.2 replay protection (last accepted
                                TOTP time-counter step; a code matching a step
                                <= this value has already been used).
  users.failed_login_attempts — consecutive failed password attempts.
  users.locked_until          — UTC time before which logins are rejected
                                without checking the password (brute-force
                                lockout).

Note: TOTP recovery codes are now stored as SHA-256 hashes in the existing
users.totp_recovery_codes JSON column (no schema change — same column, new
contents). Existing plaintext recovery codes from before this change will no
longer validate; affected users should regenerate them via /2fa/disable +
/2fa/enable.

Revision ID: 20260620_000000
Revises: 20260617_000000
Create Date: 2026-06-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260620_000000"
down_revision: Union[str, None] = "20260617_000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("totp_last_step", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("failed_login_attempts", sa.Integer(),
                                   nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("locked_until", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_attempts")
        batch.drop_column("totp_last_step")
