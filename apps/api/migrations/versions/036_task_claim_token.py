from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "036"
down_revision: str | None = "035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("creator_run_tasks", sa.Column("claim_token", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("creator_run_tasks", "claim_token")
