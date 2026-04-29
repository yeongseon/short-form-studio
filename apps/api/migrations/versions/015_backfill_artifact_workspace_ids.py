"""Backfill missing workspace IDs for artifact access control.

Revision ID: 015
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "015"
# Intentionally points to 011 for merge-time linearization; logical table prerequisites
# are documented via depends_on below so this revision can remain on the PR branch chain.
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("012", "013")


def upgrade() -> None:
    op.execute("UPDATE creator_projects SET workspace_id = 1 WHERE workspace_id IS NULL")
    op.execute("UPDATE creator_runs SET workspace_id = 1 WHERE workspace_id IS NULL")


def downgrade() -> None:
    pass
