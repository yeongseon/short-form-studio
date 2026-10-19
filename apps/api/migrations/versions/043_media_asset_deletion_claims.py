from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_media_asset_deletion_claims",
        sa.Column(
            "asset_id", sa.BigInteger(),
            sa.ForeignKey("creator_media_assets.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column(
            "claimed_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_media_asset_deletion_claims_workspace",
        "creator_media_asset_deletion_claims",
        ["workspace_id", "asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_asset_deletion_claims_workspace",
        table_name="creator_media_asset_deletion_claims",
    )
    op.drop_table("creator_media_asset_deletion_claims")
