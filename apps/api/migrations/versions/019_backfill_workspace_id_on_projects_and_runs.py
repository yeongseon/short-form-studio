"""Backfill workspace_id on projects and runs with NULL values.

Legacy rows created before workspace_id enforcement may have NULL workspace_id.
This migration assigns them the owner's first workspace.

Revision ID: 019
Revises: 018
Create Date: 2025-05-11 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Backfill projects with NULL workspace_id from the owner's first workspace
    op.execute(
        """
    UPDATE creator_projects p
    SET workspace_id = sub.workspace_id
    FROM (
        SELECT p2.id AS project_id, wm.workspace_id
        FROM creator_projects p2
        JOIN workspace_members wm ON wm.user_id = p2.user_id
        WHERE p2.workspace_id IS NULL
        ORDER BY p2.id, wm.workspace_id
    ) sub
    WHERE p.id = sub.project_id
      AND p.workspace_id IS NULL;
    """
    )

    # Backfill runs with NULL workspace_id from their project's workspace_id
    op.execute(
        """
    UPDATE creator_runs r
    SET workspace_id = p.workspace_id
    FROM creator_projects p
    WHERE r.project_id = p.id
      AND r.workspace_id IS NULL
      AND p.workspace_id IS NOT NULL;
    """
    )


def downgrade() -> None:
    # No-op: we cannot reliably distinguish backfilled rows from pre-existing ones
    pass
