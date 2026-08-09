"""Make the artifact retention window configurable via ARTIFACT_RETENTION_DAYS.

Revision ID: 031
Revises: 030
Create Date: 2026-08-09 00:00:00.000000

Migration 030 hard-coded the retention window to 90 days:

    expires_at TIMESTAMPTZ DEFAULT (NOW() + INTERVAL '90 days')

This was undocumented (no mention in README, docs/USAGE.md, or
docs/DEPLOYMENT.md) and not operator-tunable. This migration re-derives
the server default from the ``ARTIFACT_RETENTION_DAYS`` env var (default
90), so operators can adjust retention without a code change.

The default expression is only applied to NEW rows that don't specify
``expires_at`` explicitly. Existing rows keep their current value
(NULL = never expires for rows created before 030; 90 days for rows
created after 030).

Companion changes:

- ``apps/worker-orchestrator/celery_app.py`` registers a new
  ``sweep_expired_artifacts`` task in beat_schedule (every 10 minutes)
  that marks rows past ``expires_at`` as ``delete_requested_at = NOW()``.
  The existing ``retry_failed_artifact_deletions`` task then reclaims
  the storage and DB row via its ``FOR UPDATE SKIP LOCKED`` flow.
- ``.env.example``, ``README.md``, ``docs/USAGE.md`` document
  ``ARTIFACT_RETENTION_DAYS``.

See:
- ``apps/worker-orchestrator/tasks/sweep_expired_artifacts.py``
- ``apps/worker-orchestrator/tasks/retry_failed_artifact_deletions.py``
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op

revision: str = "031"
down_revision: str | None = "030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _retention_days() -> int:
    """Read ARTIFACT_RETENTION_DAYS with the same default as 030."""
    raw = os.getenv("ARTIFACT_RETENTION_DAYS", "90")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 90
    return value if value > 0 else 90


def upgrade() -> None:
    days = _retention_days()
    # Re-derive the server default from the env-driven interval so the
    # schema and application config stay in sync without a code change.
    op.execute(
        "ALTER TABLE creator_artifacts "
        f"ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '{days} days')"
    )


def downgrade() -> None:
    # Restore the hard-coded 90-day default from 030.
    op.execute(
        "ALTER TABLE creator_artifacts "
        "ALTER COLUMN expires_at SET DEFAULT (NOW() + INTERVAL '90 days')"
    )
