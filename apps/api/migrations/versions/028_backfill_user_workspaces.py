"""Backfill default workspaces for existing users and add membership indexes.

Revision ID: 028
Revises: 027
Create Date: 2025-04-01 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "028"
down_revision: str | None = "027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
    CREATE TABLE IF NOT EXISTS migration_016_created_workspaces (
        workspace_id INTEGER PRIMARY KEY
    );
    """
    )

    op.execute(
        """
    WITH users_without_membership AS (
        SELECT u.id, u.email
        FROM users u
        WHERE NOT EXISTS (
            SELECT 1
            FROM workspace_members wm
            WHERE wm.user_id = u.id
        )
    ), created_workspaces AS (
        INSERT INTO workspaces (name, slug, owner_id)
        SELECT
            u.email || '''s Workspace' AS name,
            LEFT(
                COALESCE(
                    NULLIF(
                        TRIM(BOTH '-' FROM REGEXP_REPLACE(LOWER(SPLIT_PART(u.email, '@', 1)), '[^a-z0-9]+', '-', 'g')),
                        ''
                    ),
                    'workspace'
                ),
                89
            ) || '-' || u.id::text AS slug,
            u.id AS owner_id
        FROM users_without_membership u
        RETURNING id, owner_id
    ), tracked_workspaces AS (
        INSERT INTO migration_016_created_workspaces (workspace_id)
        SELECT DISTINCT cw.id
        FROM created_workspaces cw
        ON CONFLICT (workspace_id) DO NOTHING
        RETURNING workspace_id
    )
    INSERT INTO workspace_members (workspace_id, user_id, role)
    SELECT cw.id, cw.owner_id, 'owner'
    FROM created_workspaces cw
    JOIN tracked_workspaces tw ON tw.workspace_id = cw.id;
    """
    )

    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_workspace_members_workspace_id", table_name="workspace_members")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")

    op.execute(
        """
    DELETE FROM workspace_members
    WHERE workspace_id IN (
        SELECT workspace_id FROM migration_016_created_workspaces
    );
    """
    )

    op.execute(
        """
    DELETE FROM workspaces
    WHERE id IN (
        SELECT workspace_id FROM migration_016_created_workspaces
    );
    """
    )

    op.execute("DROP TABLE IF EXISTS migration_016_created_workspaces;")
