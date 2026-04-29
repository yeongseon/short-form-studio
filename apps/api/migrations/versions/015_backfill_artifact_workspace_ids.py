"""Backfill missing workspace IDs for artifact access control.

Revision ID: 015
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE creator_projects SET workspace_id = 1 WHERE workspace_id IS NULL")
    op.execute("UPDATE creator_runs SET workspace_id = 1 WHERE workspace_id IS NULL")


def downgrade() -> None:
    pass
