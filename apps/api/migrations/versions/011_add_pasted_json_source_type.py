"""Add pasted_json to source_type check constraint.

Revision ID: 011
Revises: 010
Create Date: 2025-04-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
