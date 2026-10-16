from __future__ import annotations

BEAT_SCHEDULE: dict[str, dict[str, str | float]] = {
    "reconcile-stale-dispatches": {
        "task": "reconcile_stale_dispatches",
        "schedule": 60.0,
    },
    "retry-failed-artifact-deletions": {
        "task": "retry_failed_artifact_deletions",
        "schedule": 300.0,
    },
    "sweep-expired-artifacts": {
        "task": "sweep_expired_artifacts",
        "schedule": 600.0,
    },
    "reconcile-media-uploads": {
        "task": "reconcile_media_uploads",
        "schedule": 600.0,
    },
    "sweep-media-retention": {
        "task": "sweep_media_retention",
        "schedule": 3600.0,
    },
}
