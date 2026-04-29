"""Add workspace_id to creator_projects and creator_runs.

Revision ID: 013
Revises: 012
Create Date: 2025-04-01 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("creator_projects", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("creator_runs", sa.Column("workspace_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_creator_projects_workspace_id_workspaces",
        "creator_projects",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_creator_runs_workspace_id_workspaces",
        "creator_runs",
        "workspaces",
        ["workspace_id"],
        ["id"],
    )

    op.create_index("ix_creator_projects_workspace_id", "creator_projects", ["workspace_id"])
    op.create_index("ix_creator_runs_workspace_id", "creator_runs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_creator_runs_workspace_id")
    op.drop_index("ix_creator_projects_workspace_id")
    op.drop_constraint(
        "fk_creator_runs_workspace_id_workspaces", "creator_runs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_creator_projects_workspace_id_workspaces", "creator_projects", type_="foreignkey"
    )
    op.drop_column("creator_runs", "workspace_id")
    op.drop_column("creator_projects", "workspace_id")
