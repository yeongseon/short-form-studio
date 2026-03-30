from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel


class AudioArtifact(BaseModel):
    id: int
    run_id: int
    path: str
    model_used: str | None = None
    provider_type: str | None = None
    voice: str | None = None
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> AudioArtifact:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict) -> AudioArtifact:
        """Construct from a creator_artifacts DB row.

        The creator_artifacts table stores artifact-specific fields in
        metadata_json.  This method extracts model_used, provider_type,
        and voice from that JSON column and maps file_path -> path.
        """
        mapped = dict(row)
        if "file_path" in mapped and "path" not in mapped:
            mapped["path"] = mapped.pop("file_path")
        # Extract domain fields from metadata_json
        raw_meta = mapped.pop("metadata_json", None)
        if raw_meta is not None:
            meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
            mapped.setdefault("model_used", meta.get("model_used"))
            mapped.setdefault("provider_type", meta.get("provider_type"))
            mapped.setdefault("voice", meta.get("voice"))
        # Discard DB-only columns not in this domain model
        for key in ("artifact_type", "scene_id", "file_size_bytes", "mime_type", "updated_at"):
            mapped.pop(key, None)
        return cls.model_validate(mapped)

    def to_json(self) -> str:
        return self.model_dump_json()
