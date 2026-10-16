from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_media_upload_intents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "workspace_id", sa.Integer(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("storage_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('pending', 'uploaded', 'cleanup_pending', 'completed', 'reclaimed', 'exhausted')",
            name="ck_media_upload_intents_state",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_media_upload_intents_retry_count"),
        sa.CheckConstraint(
            "storage_key LIKE ('workspaces/' || workspace_id::text || '/assets/%')",
            name="ck_media_upload_intents_owned_key",
        ),
    )
    op.create_index(
        "ix_media_upload_intents_reconcile",
        "creator_media_upload_intents", ["state", "lease_expires_at", "id"],
    )


def downgrade() -> None:
    op.drop_table("creator_media_upload_intents")
