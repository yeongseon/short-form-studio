"""Backfill default workspaces for existing users and add membership indexes.

Revision ID: 016
Revises: 011
Create Date: 2025-04-01 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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
    )
    INSERT INTO workspace_members (workspace_id, user_id, role)
    SELECT cw.id, cw.owner_id, 'owner'
    FROM created_workspaces cw;
    """
    )

    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])

    # Follow-up plan (not enforced in this migration):
    # 1) Backfill users.workspace_id from each user's primary workspace membership.
    # 2) Enforce users.workspace_id as NOT NULL after all rows are populated.


def downgrade() -> None:
    op.drop_index("ix_workspace_members_workspace_id")
    op.drop_index("ix_workspace_members_user_id")
