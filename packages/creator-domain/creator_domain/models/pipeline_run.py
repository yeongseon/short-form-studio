from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import ClassVar
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from .model_selection import ModelSelection
from .stage import RunStage


logger = logging.getLogger(__name__)


class PipelineRun(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    project_id: int = Field(ge=1)
    current_stage: RunStage | None = None
    status: Literal["pending", "running", "paused", "completed", "failed", "cancelled"] = "pending"
    review_stage: RunStage | None = None
    restart_from: RunStage | None = None
    model_defaults: ModelSelection | None = None
    metadata: dict[str, object] | None = None
    style_preset: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=0, default=0)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PipelineRun:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> PipelineRun:
        """Construct from a DB row dict, mapping column names to domain fields.

        Handles:
        - model_defaults_json (TEXT) -> model_defaults (ModelSelection | None)
        - metadata_json (TEXT) -> metadata (dict | None)
        """
        mapped = dict(row)
        _ = mapped.pop("workspace_id", None)
        raw_defaults = mapped.pop("model_defaults_json", None)
        if raw_defaults is not None:
            try:
                mapped["model_defaults"] = cast(
                    dict[str, object], json.loads(cast(str, raw_defaults))
                )
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Malformed JSON in model_defaults_json column for row id=%s", mapped.get("id")
                )
                mapped["model_defaults"] = None
        raw_meta = mapped.pop("metadata_json", None)
        if raw_meta is not None:
            try:
                mapped["metadata"] = cast(dict[str, object], json.loads(cast(str, raw_meta)))
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Malformed JSON in metadata_json column for row id=%s", mapped.get("id")
                )
                mapped["metadata"] = None
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
