"""Add artifact access control metadata columns.

Revision ID: 014
Revises: 011
Create Date: 2026-04-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creator_artifacts",
        sa.Column(
            "workspace_id",
            sa.Integer(),
            nullable=True,
            comment="FK to workspaces.id — enforced after workspace PR is merged",
        ),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("creator_projects.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column(
            "storage_provider",
            sa.String(length=50),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("content_type", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("checksum", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "creator_artifacts",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_creator_artifacts_workspace_run",
        "creator_artifacts",
        ["workspace_id", "run_id"],
    )

    # TODO(#385): Populate workspace_id/project_id for artifacts once workspace
    # ownership is integrated into run/project creation flow.


def downgrade() -> None:
    op.drop_index("ix_creator_artifacts_workspace_run", "creator_artifacts")
    op.drop_column("creator_artifacts", "expires_at")
    op.drop_column("creator_artifacts", "checksum")
    op.drop_column("creator_artifacts", "content_type")
    op.drop_column("creator_artifacts", "storage_provider")
    op.drop_column("creator_artifacts", "project_id")
    op.drop_column("creator_artifacts", "workspace_id")
