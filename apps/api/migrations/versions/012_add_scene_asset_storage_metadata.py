"""Add storage metadata columns to creator_scene_assets.

Revision ID: 012
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_scene_assets",
        sa.Column("storage_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "creator_scene_assets",
        sa.Column("storage_key", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_scene_assets", "storage_key")
    op.drop_column("creator_scene_assets", "storage_provider")
