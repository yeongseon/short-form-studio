"""Add per-paragraph artifact index.

Revision ID: 008
Revises: 007
Create Date: 2026-03-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for efficient per-paragraph artifact lookups.
    # Queries like: SELECT * FROM creator_artifacts
    #   WHERE run_id = $1 AND scene_id = $2 AND artifact_type = $3
    op.create_index(
        "ix_creator_artifacts_run_scene_type",
        "creator_artifacts",
        ["run_id", "scene_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_creator_artifacts_run_scene_type", "creator_artifacts")
