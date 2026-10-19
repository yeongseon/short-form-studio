from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "042"
down_revision: str | None = "041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creator_broker_state",
        sa.Column("singleton", sa.Boolean(), primary_key=True),
        sa.Column("epoch", sa.String(255), nullable=False),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("singleton", name="ck_creator_broker_state_singleton"),
    )


def downgrade() -> None:
    op.drop_table("creator_broker_state")
