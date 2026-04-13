"""Add pasted_json to source_type check constraint.

Revision ID: 011
Revises: 010
Create Date: 2025-04-01 00:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old constraint and recreate with pasted_json included
    op.drop_constraint("ck_creator_projects_source_type", "creator_projects")
    op.create_check_constraint(
        "ck_creator_projects_source_type",
        "creator_projects",
        "source_type IN ('idea', 'markdown', 'url', 'pasted_json')",
    )

    # Add json_script column for storing raw JSON input
    op.add_column(
        "creator_projects",
        sa.Column("json_script", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creator_projects", "json_script")
    op.drop_constraint("ck_creator_projects_source_type", "creator_projects")
    op.create_check_constraint(
        "ck_creator_projects_source_type",
        "creator_projects",
        "source_type IN ('idea', 'markdown', 'url')",
    )
