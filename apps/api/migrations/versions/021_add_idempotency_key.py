"""Add idempotency_key columns for worker dedup.

Revision ID: 021
Revises: 020
Create Date: 2026-05-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = (
        "creator_artifacts",
        "creator_script_drafts",
        "creator_visual_plans",
        "creator_scene_assets",
    )
    for table in tables:
        op.add_column(table, sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        op.create_index(f"ix_{table}_idempotency_key", table, ["idempotency_key"], unique=True)


def downgrade() -> None:
    tables = (
        "creator_artifacts",
        "creator_script_drafts",
        "creator_visual_plans",
        "creator_scene_assets",
    )
    for table in tables:
        op.drop_index(f"ix_{table}_idempotency_key", table_name=table)
        op.drop_column(table, "idempotency_key")
