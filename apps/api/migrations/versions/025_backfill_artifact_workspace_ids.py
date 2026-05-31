"""Backfill missing workspace IDs for artifact access control.

Revision ID: 025
Revises: 024
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE creator_artifacts SET workspace_id = cr.workspace_id
        FROM creator_runs cr
        WHERE creator_artifacts.run_id = cr.id
          AND creator_artifacts.workspace_id IS NULL
          AND cr.workspace_id IS NOT NULL
        """
    )


def downgrade() -> None:
    pass
