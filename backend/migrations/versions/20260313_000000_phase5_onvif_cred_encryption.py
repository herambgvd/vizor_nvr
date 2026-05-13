"""Phase 5.2 — widen ONVIF credential columns for AES-GCM ciphertext

Revision ID: 011_phase5_onvif_cred_encryption
Revises: 010_perf_composite_indexes
Create Date: 2026-03-13 00:00:00

ONVIF username/password are now encrypted at rest (Fernet token, prefixed
'enc:'). Ciphertext is ~3x plaintext length plus a header, so the legacy
String(100) columns overflow on real credentials. Widen to String(500).

Re-encryption of legacy plaintext rows happens at startup in
app.core.crypto.backfill_encrypt_credentials() — this migration only
adjusts column width so the encrypted values fit.
"""
from alembic import op
import sqlalchemy as sa


revision = "011_phase5_onvif_cred_encryption"
down_revision = "010_perf_composite_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.alter_column(
            "onvif_username",
            existing_type=sa.String(length=100),
            type_=sa.String(length=500),
            existing_nullable=True,
        )
        batch.alter_column(
            "onvif_password",
            existing_type=sa.String(length=100),
            type_=sa.String(length=500),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("cameras") as batch:
        batch.alter_column(
            "onvif_password",
            existing_type=sa.String(length=500),
            type_=sa.String(length=100),
            existing_nullable=True,
        )
        batch.alter_column(
            "onvif_username",
            existing_type=sa.String(length=500),
            type_=sa.String(length=100),
            existing_nullable=True,
        )
