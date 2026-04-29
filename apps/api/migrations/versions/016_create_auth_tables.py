"""Create auth tables for API key workspace resolution.

Revision ID: 016
Revises: 015
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            auth_subject VARCHAR(255) UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_members (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, workspace_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            key_hash VARCHAR(64) NOT NULL UNIQUE,
            revoked_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_key_hash ON api_keys (key_hash)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspace_members_user_id ON workspace_members (user_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_workspace_members_user_id")
    op.execute("DROP INDEX IF EXISTS ix_api_keys_key_hash")
    op.execute("DROP TABLE IF EXISTS api_keys")
    op.execute("DROP TABLE IF EXISTS workspace_members")
    op.execute("DROP TABLE IF EXISTS workspaces")
    op.execute("DROP TABLE IF EXISTS users")
