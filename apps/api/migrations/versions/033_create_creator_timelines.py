"""Create creator_timelines: one authoritative timeline per project.

Revision ID: 033
Revises: 032
Create Date: 2026-09-21 00:00:00.000000

SF-28 persists one editable Timeline per Project. The table is keyed by
``project_id`` (one-to-one with creator_projects), stores a derived
``workspace_id`` for scoped queries (consistent with creator_runs), and a
``revision`` column that is both the domain revision and the optimistic-
concurrency counter. Segments are stored as JSON text, mirroring the existing
``*_json`` columns.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "033"
down_revision: str | None = "032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_timelines",
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("creator_projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("timeline_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("segments_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("revision >= 0", name="ck_creator_timelines_revision_nonneg"),
    )
    op.create_index(
        "ix_creator_timelines_workspace_project",
        "creator_timelines",
        ["workspace_id", "project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_timelines_workspace_project", table_name="creator_timelines")
    op.drop_table("creator_timelines")
