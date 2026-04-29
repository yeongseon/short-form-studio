"""Create api_keys table for artifact access control."""

from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
    )


def downgrade():
    op.drop_table("api_keys")
