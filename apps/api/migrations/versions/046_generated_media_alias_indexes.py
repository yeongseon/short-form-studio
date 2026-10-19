from collections.abc import Sequence

from alembic import op

revision: str = "046"
down_revision: str | None = "045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_scene_assets_storage_key", "creator_scene_assets", ["storage_key"],
    )
    op.create_index(
        "ix_artifacts_storage_key", "creator_artifacts", ["storage_key"],
    )
    op.create_index(
        "ix_media_assets_storage_key", "creator_media_assets", ["storage_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_assets_storage_key", table_name="creator_media_assets")
    op.drop_index("ix_artifacts_storage_key", table_name="creator_artifacts")
    op.drop_index("ix_scene_assets_storage_key", table_name="creator_scene_assets")
