"""Add ``name`` and ``revoked_at`` columns to api_keys.

Revision ID: 029
Revises: 028
Create Date: 2026-07-18 00:00:00.000000

Closes a production-blocking schema drift:

- ``apps/api/src/shorts_api/auth.py`` queries
  ``SELECT ... FROM api_keys WHERE revoked_at IS NULL`` (lines 84, 265).
- ``scripts/create_api_key.py`` inserts into
  ``api_keys (user_id, key_hash, name)`` (line 56).
- ``apps/api/migrations/versions/018_api_keys_and_quota_unit_rename.py``
  created ``api_keys`` with only ``(id, user_id, key_hash, created_at)`` —
  missing both ``name`` and ``revoked_at``.

Result: any code path that hit these columns raised
``UndefinedColumn: column "revoked_at" does not exist`` on first production
boot. The test suite masked the bug because ``conftest.py`` stubs the DB
layer at the SQL boundary.

This migration adds both columns as nullable so existing rows remain valid:

- ``name`` (TEXT, nullable): human label for the key, set at creation time
  by ``scripts/create_api_key.py``. Not used for auth decisions, so nullable
  is safe for backfill of any pre-existing rows.
- ``revoked_at`` (TIMESTAMPTZ, nullable): set when the key is revoked via
  admin action. ``auth.py`` filters ``WHERE revoked_at IS NULL`` to reject
  revoked keys; nullable is correct because NULL == "not revoked".

Revoking a key (operator action until a revoke API ships)::

    UPDATE api_keys SET revoked_at = NOW() WHERE id = <key_id>;

A future ``/api/admin/api-keys/{id}/revoke`` endpoint will automate this.

Lock notes:

- ``add_column ... nullable`` is metadata-only (no table rewrite, no scan).
- ``CREATE INDEX`` (without ``CONCURRENTLY``) acquires SHARE lock, blocking
  concurrent writes. For the typical small ``api_keys`` table (<1000 rows)
  this is negligible. For very large tables, split the index creation into
  a separate migration using ``CREATE INDEX CONCURRENTLY`` via Alembic's
  ``autocommit_block()``.

See ``apps/api/tests/test_api_keys_schema.py`` for the regression test.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "029"
down_revision: str | None = "028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("name", sa.Text(), nullable=True),
    )
    op.add_column(
        "api_keys",
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Soft index: speed up ``WHERE revoked_at IS NULL`` lookups on hot auth path.
    # Partial index keeps it small (only non-revoked rows) and matches the query shape.
    op.execute(
        "CREATE INDEX ix_api_keys_active_key_hash ON api_keys (key_hash) WHERE revoked_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_keys_active_key_hash")
    op.drop_column("api_keys", "revoked_at")
    op.drop_column("api_keys", "name")
