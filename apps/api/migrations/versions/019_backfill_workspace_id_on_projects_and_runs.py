"""Backfill workspace_id on runs from their parent project.

Legacy runs created before workspace_id enforcement may have NULL workspace_id.
This migration copies workspace_id from the parent project where available.

Note: creator_projects has no user_id column, so orphaned projects with
NULL workspace_id cannot be automatically backfilled and require manual
intervention via admin tooling.

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
