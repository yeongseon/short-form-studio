"""Add storage metadata columns to artifact tables.

Revision ID: 023
Revises: 022
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: str | None = "022"
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
    op.add_column(
        "creator_artifacts",
        sa.Column("storage_backend", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("storage_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("content_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_artifacts", "size_bytes")
    op.drop_column("creator_artifacts", "content_type")
    op.drop_column("creator_artifacts", "storage_key")
    op.drop_column("creator_artifacts", "storage_backend")
    op.drop_column("creator_scene_assets", "storage_key")
    op.drop_column("creator_scene_assets", "storage_provider")
