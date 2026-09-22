"""Add canonical media metadata without modifying legacy scene assets (033 -> 034)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_media_assets",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("creator_projects.id", ondelete="SET NULL")),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("creator_runs.id", ondelete="SET NULL")),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(1024)),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("media_type IN ('IMAGE', 'VIDEO', 'AUDIO', 'LOGO', 'GRAPHIC')", name="ck_media_assets_type"),
        sa.CheckConstraint(
            "origin IN ('UPLOADED', 'IMPORTED', 'EXTERNAL_URL', 'STOCK', 'GENERATED')",
            name="ck_media_assets_origin",
        ),
        sa.CheckConstraint("width >= 0 AND height >= 0 AND duration_seconds >= 0", name="ck_media_assets_dimensions"),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name="ck_media_assets_metadata"),
    )
    op.create_index(
        "ix_media_assets_workspace_project_type", "creator_media_assets",
        ["workspace_id", "project_id", "media_type"],
    )
    op.create_index(
        "ix_media_assets_workspace_created", "creator_media_assets", ["workspace_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("creator_media_assets")
