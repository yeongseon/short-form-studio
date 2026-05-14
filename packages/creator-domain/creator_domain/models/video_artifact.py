from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field


logger = logging.getLogger(__name__)


class VideoArtifact(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    run_id: int = Field(ge=1)
    path: str = Field(max_length=1024)
    render_profile: str | None = None
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> VideoArtifact:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> VideoArtifact:
        """Construct from a creator_artifacts DB row.

        The creator_artifacts table stores artifact-specific fields in
        metadata_json.  This method extracts render_profile from that JSON
        column and maps file_path -> path.
        """
        mapped = dict(row)
        if "file_path" in mapped and "path" not in mapped:
            mapped["path"] = mapped.pop("file_path")
        # Extract domain fields from metadata_json
        raw_meta = mapped.pop("metadata_json", None)
        if raw_meta is not None:
            try:
                meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Malformed JSON in metadata_json column for row id=%s", mapped.get("id")
                )
                meta = None
            if not isinstance(meta, dict):
                meta = None
        else:
            meta = None
        if meta is not None:
            meta_dict = cast(dict[str, object], meta)
            _ = mapped.setdefault("render_profile", meta_dict.get("render_profile"))
        # Discard DB-only columns not in this domain model
        for key in ("artifact_type", "scene_id", "file_size_bytes", "mime_type", "updated_at"):
            _ = mapped.pop(key, None)
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
