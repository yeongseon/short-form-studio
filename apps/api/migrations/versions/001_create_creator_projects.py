"""Create creator_projects table.

Revision ID: 001
Revises: None
Create Date: 2025-01-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "creator_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="idea"),
        sa.Column("idea_brief", sa.Text(), nullable=True),
        sa.Column("markdown_source", sa.Text(), nullable=True),
        sa.Column("url_source", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_check_constraint(
        "ck_creator_projects_source_type",
        "creator_projects",
        "source_type IN ('idea', 'markdown', 'url')",
    )
    op.create_check_constraint(
        "ck_creator_projects_status",
        "creator_projects",
        "status IN ('draft', 'active', 'completed', 'archived')",
    )

    op.execute(
        """
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
    )
    op.execute(
        """
    CREATE TRIGGER set_updated_at
    BEFORE UPDATE ON creator_projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
    """
    )

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS set_updated_at ON creator_projects")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column()")
    op.drop_constraint("ck_creator_projects_source_type", "creator_projects")
    op.drop_constraint("ck_creator_projects_status", "creator_projects")
    op.drop_table("creator_projects")
