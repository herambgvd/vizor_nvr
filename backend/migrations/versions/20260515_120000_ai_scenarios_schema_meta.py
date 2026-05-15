"""
ai_scenarios — camera_config_schema + module_tabs

Adds two metadata columns that drive frontend rendering:
  - camera_config_schema: JSON Schema describing the per-camera config
    form fields (toggle, ROI canvas, threshold, etc).
  - module_tabs: list of sub-tabs the AI Modules workspace should
    render for this scenario (live, events, analytics, persons,
    attendance, investigate, groups).

Revision ID: ai_scenarios_schema_meta
Revises: camera_display_order
"""
from alembic import op
import sqlalchemy as sa


revision = "ai_scenarios_schema_meta"
down_revision = "camera_display_order"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_scenarios",
        sa.Column("camera_config_schema", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ai_scenarios",
        sa.Column("module_tabs", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("ai_scenarios", "module_tabs")
    op.drop_column("ai_scenarios", "camera_config_schema")
