from typing import Final

UPDATABLE_RUN_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "current_stage",
        "status",
        "review_stage",
        "restart_from",
        "model_defaults_json",
        "metadata_json",
        "style_preset",
        "started_at",
        "finished_at",
    }
)
