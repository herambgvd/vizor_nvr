"""report schedules + runs + camera names (PPE reports/dashboard enhance)

Revision ID: ppe_0003_reports
Revises: ppe_0002_public_ingest
"""
from alembic import op
import sqlalchemy as sa

revision = "ppe_0003_reports"
down_revision = "ppe_0002_public_ingest"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ppe_camera_names",
        sa.Column("camera_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "ppe_report_schedules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("report", sa.String(length=30), nullable=False),
        sa.Column("fmt", sa.String(length=10), nullable=False, server_default="xlsx"),
        sa.Column("frequency", sa.String(length=10), nullable=False, server_default="daily"),
        sa.Column("at_time", sa.String(length=5), nullable=False, server_default="08:00"),
        sa.Column("range_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recipients", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "ppe_report_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schedule_id", sa.String(), nullable=True),
        sa.Column("report", sa.String(length=30), nullable=False),
        sa.Column("fmt", sa.String(length=10), nullable=False),
        sa.Column("filename", sa.String(length=300), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("emailed_to", sa.Text(), nullable=True),
        sa.Column("email_ok", sa.Boolean(), nullable=True),
        sa.Column("rows", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ppe_report_runs")
    op.drop_table("ppe_report_schedules")
    op.drop_table("ppe_camera_names")
