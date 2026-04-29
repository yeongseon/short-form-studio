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
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'workspace_members'
            ) AND EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'creator_projects' AND column_name = 'created_by'
            ) THEN
                UPDATE creator_projects cp
                SET workspace_id = wm.workspace_id
                FROM LATERAL (
                    SELECT workspace_id
                    FROM workspace_members
                    WHERE user_id = cp.created_by
                    ORDER BY workspace_id
                    LIMIT 1
                ) AS wm
                WHERE cp.workspace_id IS NULL;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            UPDATE creator_runs r
            SET workspace_id = p.workspace_id
            FROM creator_projects p
            WHERE r.project_id = p.id
              AND p.workspace_id IS NOT NULL
              AND r.workspace_id IS NULL;
        END $$;
        """
    )


def downgrade() -> None:
    pass
