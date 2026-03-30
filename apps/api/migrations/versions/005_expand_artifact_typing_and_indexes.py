"""Expand artifact typing and add creator indexes.

Revision ID: 005
Revises: 004
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Create creator_artifacts table ---
    op.create_table(
        "creator_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("creator_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=50), nullable=False),
        sa.Column("scene_id", sa.String(length=100), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # CHECK constraint for artifact_type
    op.create_check_constraint(
        "ck_creator_artifacts_artifact_type",
        "creator_artifacts",
        "artifact_type IN ("
        "'idea', 'script', 'visual_plan', 'visual_asset', "
        "'audio', 'subtitle', 'video', 'render_manifest'"
        ")",
    )

    # Conditional CHECK: visual_asset requires scene_id
    op.create_check_constraint(
        "ck_creator_artifacts_visual_asset_scene_id",
        "creator_artifacts",
        "artifact_type <> 'visual_asset' OR scene_id IS NOT NULL",
    )

    # updated_at trigger (reuses function from migration 001)
    op.execute(
        """
    CREATE TRIGGER set_updated_at_creator_artifacts
    BEFORE UPDATE ON creator_artifacts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
    """
    )

    # --- 2. Indexes on creator_artifacts (from DB_MIGRATION.md §6) ---
    op.create_index(
        "ix_creator_artifacts_run_type",
        "creator_artifacts",
        ["run_id", "artifact_type"],
    )
    op.execute(
        """
    CREATE INDEX ix_creator_artifacts_run_type_created
    ON creator_artifacts (run_id, artifact_type, created_at DESC);
    """
    )

    # --- 3. Missing indexes on existing creator tables (from DB_MIGRATION.md §6) ---
    # creator_projects: sort by newest first
    op.execute(
        """
    CREATE INDEX ix_creator_projects_created_at_desc
    ON creator_projects (created_at DESC);
    """
    )
    # creator_runs: lookup by project sorted by newest first
    op.execute(
        """
    CREATE INDEX ix_creator_runs_project_created_desc
    ON creator_runs (project_id, created_at DESC);
    """
    )
    # creator_runs: filter by current_stage
    op.create_index(
        "ix_creator_runs_current_stage",
        "creator_runs",
        ["current_stage"],
    )
    # Drop redundant single-column index from 002 — superseded by composite above
    op.drop_index("ix_creator_runs_project_id", "creator_runs")


def downgrade() -> None:
    # Drop indexes on existing tables (reverse order)
    op.drop_index("ix_creator_runs_current_stage", "creator_runs")
    op.drop_index("ix_creator_runs_project_created_desc", "creator_runs")
    op.drop_index("ix_creator_projects_created_at_desc", "creator_projects")
    # Re-create the single-column index that was dropped in upgrade
    op.create_index("ix_creator_runs_project_id", "creator_runs", ["project_id"])

    # Drop creator_artifacts indexes, trigger, constraint, table
    op.drop_index("ix_creator_artifacts_run_type_created", "creator_artifacts")
    op.drop_index("ix_creator_artifacts_run_type", "creator_artifacts")
    op.execute(
        "DROP TRIGGER IF EXISTS set_updated_at_creator_artifacts ON creator_artifacts"
    )
    op.drop_constraint("ck_creator_artifacts_visual_asset_scene_id", "creator_artifacts")
    op.drop_constraint("ck_creator_artifacts_artifact_type", "creator_artifacts")
    op.drop_table("creator_artifacts")
