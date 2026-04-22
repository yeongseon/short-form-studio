"""Create creator_scene_assets table.

Revision ID: 004
Revises: 003
Create Date: 2025-01-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "creator_scene_assets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("creator_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("asset_path", sa.Text(), nullable=False),
        sa.Column("prompt_snapshot", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Index for lookups by run + scene
    op.create_index(
        "ix_creator_scene_assets_run_scene",
        "creator_scene_assets",
        ["run_id", "scene_id"],
    )

    # Index for active asset lookups
    op.create_index(
        "ix_creator_scene_assets_active",
        "creator_scene_assets",
        ["run_id", "scene_id", "is_active"],
    )

    # Unique constraint: no duplicate version per scene
    op.create_unique_constraint(
        "uq_creator_scene_assets_run_scene_version",
        "creator_scene_assets",
        ["run_id", "scene_id", "version"],
    )

    # Partial unique index: only one active asset per scene
    op.execute(
        """
    CREATE UNIQUE INDEX uq_creator_scene_assets_active
    ON creator_scene_assets (run_id, scene_id)
    WHERE is_active = true;
    """
    )

def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_creator_scene_assets_active")
    op.drop_constraint("uq_creator_scene_assets_run_scene_version", "creator_scene_assets")
    op.drop_index("ix_creator_scene_assets_active")
    op.drop_index("ix_creator_scene_assets_run_scene")
    op.drop_table("creator_scene_assets")
