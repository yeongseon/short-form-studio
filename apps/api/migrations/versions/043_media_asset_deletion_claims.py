from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "043"
down_revision: str | None = "042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_media_assets",
        sa.Column("deleting", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_media_assets_workspace_deleting",
        "creator_media_assets",
        ["workspace_id", "deleting"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_workspace_deleting", table_name="creator_media_assets")
    op.drop_column("creator_media_assets", "deleting")
