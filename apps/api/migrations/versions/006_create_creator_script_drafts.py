from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_script_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("creator_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("markdown_content", sa.Text(), nullable=True),
        sa.Column("structured_script_json", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_index("ix_creator_script_drafts_run_id", "creator_script_drafts", ["run_id"])
    op.create_unique_constraint(
        "uq_creator_script_drafts_run_version",
        "creator_script_drafts",
        ["run_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_creator_script_drafts_run_version", "creator_script_drafts")
    op.drop_index("ix_creator_script_drafts_run_id")
    op.drop_table("creator_script_drafts")
