"""Phase 4 — Storage protection & integrity

Revision ID: 012_phase4_storage_protection
Revises: 011_phase5_onvif_cred_encryption
Create Date: 2026-03-14 00:00:00

Schema additions to support:
  4.1  multi-pool failover     — storage_pools.pool_type widened, mount_options
  4.2  S.M.A.R.T monitoring    — disk_health_snapshots
  4.4  redundant recording     — cameras.redundancy_enabled, recordings.redundant_path
  4.5  recording integrity     — recordings.checksum, recordings.integrity_status
  4.7  per-camera cloud backup — cameras.cloud_backup_enabled
"""
from alembic import op
import sqlalchemy as sa


revision = "012_phase4_storage_protection"
down_revision = "011_phase5_onvif_cred_encryption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── recordings: integrity + mirror columns ──────────────────────────
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("checksum", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("integrity_status", sa.String(length=20),
                                   nullable=True, server_default="unchecked"))
        batch.add_column(sa.Column("redundant_path", sa.String(length=500), nullable=True))

    # ── cameras: redundancy + cloud backup toggles ──────────────────────
    with op.batch_alter_table("cameras") as batch:
        batch.add_column(sa.Column("redundancy_enabled", sa.Boolean(),
                                   nullable=True, server_default=sa.text("false")))
        batch.add_column(sa.Column("cloud_backup_enabled", sa.Boolean(),
                                   nullable=True, server_default=sa.text("false")))

    # ── disk_health_snapshots ──────────────────────────────────────────
    op.create_table(
        "disk_health_snapshots",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("device", sa.String(length=120), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("serial", sa.String(length=120), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("temperature_c", sa.Integer(), nullable=True),
        sa.Column("power_on_hours", sa.Integer(), nullable=True),
        sa.Column("reallocated_sectors", sa.Integer(), nullable=True),
        sa.Column("pending_sectors", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)")),
    )
    op.create_index("ix_disk_health_device_captured",
                    "disk_health_snapshots", ["device", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_disk_health_device_captured", table_name="disk_health_snapshots")
    op.drop_table("disk_health_snapshots")
    with op.batch_alter_table("cameras") as batch:
        batch.drop_column("cloud_backup_enabled")
        batch.drop_column("redundancy_enabled")
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("redundant_path")
        batch.drop_column("integrity_status")
        batch.drop_column("checksum")
