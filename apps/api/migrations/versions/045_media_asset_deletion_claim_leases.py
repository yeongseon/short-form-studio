from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "045"
down_revision: str | None = "044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_media_asset_deletion_claims",
        sa.Column(
            "claim_token", sa.Text(), nullable=True,
            server_default=sa.text("md5(random()::text || clock_timestamp()::text)"),
        ),
    )
    op.add_column(
        "creator_media_asset_deletion_claims",
        sa.Column(
            "lease_expires_at", sa.DateTime(timezone=True), nullable=True,
            server_default=sa.text("now() + interval '15 minutes'"),
        ),
    )
    op.execute(
        """UPDATE creator_media_asset_deletion_claims
            SET claim_token = md5(random()::text || clock_timestamp()::text),
                lease_expires_at = now()
            WHERE claim_token IS NULL"""
    )
    op.alter_column("creator_media_asset_deletion_claims", "claim_token", nullable=False)
    op.alter_column("creator_media_asset_deletion_claims", "lease_expires_at", nullable=False)


def downgrade() -> None:
    op.drop_column("creator_media_asset_deletion_claims", "lease_expires_at")
    op.drop_column("creator_media_asset_deletion_claims", "claim_token")
