from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: str | None = "046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_approved_timeline_assets",
        sa.Column(
            "review_id", sa.Integer(),
            sa.ForeignKey("creator_stage_reviews.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("timeline_id", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "asset_id", sa.BigInteger(),
            sa.ForeignKey("creator_media_assets.id", ondelete="CASCADE"), primary_key=True,
        ),
    )
    op.create_index(
        "ix_approved_timeline_assets_workspace_asset",
        "creator_approved_timeline_assets",
        ["workspace_id", "asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approved_timeline_assets_workspace_asset",
        table_name="creator_approved_timeline_assets",
    )
    op.drop_table("creator_approved_timeline_assets")
