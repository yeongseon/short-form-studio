from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_media_upload_intents",
        sa.Column("reserved_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_media_upload_intents_reserved_bytes",
        "creator_media_upload_intents",
        "reserved_bytes >= 0",
    )
    op.create_index(
        "ix_media_upload_intents_workspace_reservations",
        "creator_media_upload_intents",
        ["workspace_id", "state"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_upload_intents_workspace_reservations",
        table_name="creator_media_upload_intents",
    )
    op.drop_constraint(
        "ck_media_upload_intents_reserved_bytes",
        "creator_media_upload_intents",
        type_="check",
    )
    op.drop_column("creator_media_upload_intents", "reserved_bytes")
