from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from .media_type import MediaOrigin, MediaType

if TYPE_CHECKING:
    from .visual_asset import VisualAsset


class MediaAsset(BaseModel):
    """Generic media asset for the short-first, long-form-ready media core.

    Represents uploaded, generated, external, stock, or imported media without a
    short-only duration ceiling. Short form is a product constraint, not a core
    domain constraint, so this model stays media-first and reusable.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", protected_namespaces=())

    id: int = Field(ge=1)
    workspace_id: int = Field(ge=1)
    project_id: int | None = Field(default=None, ge=1)
    run_id: int | None = Field(default=None, ge=1)
    media_type: MediaType
    origin: MediaOrigin
    storage_key: str | None = Field(default=None, max_length=1024)
    mime_type: str | None = Field(default=None, max_length=255)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    source_url: str | None = Field(default=None, max_length=2048)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> MediaAsset:
        return cls.model_validate(data)

    @classmethod
    def from_row(cls, row: dict[str, object]) -> MediaAsset:
        """Construct from a DB row dict, dropping unknown columns."""
        known = set(cls.model_fields)
        filtered = {key: value for key, value in row.items() if key in known}
        return cls.model_validate(filtered)

    @classmethod
    def from_visual_asset(
        cls,
        visual: VisualAsset,
        *,
        workspace_id: int,
        project_id: int | None = None,
    ) -> MediaAsset:
        """Adapt a legacy ``VisualAsset`` (AI-generated image) into a MediaAsset.

        Scene selection (``scene_id``), version, active state, and generation
        provenance are preserved in ``metadata`` so nothing is lost, and the
        original ``VisualAsset`` id is recorded to avoid duplicating records.
        ``storage_key`` falls back to ``asset_path`` so existing artifacts stay
        reachable. Callers supply ``workspace_id`` since VisualAsset predates the
        workspace model.
        """
        if workspace_id < 1:
            raise ValueError("workspace_id must be >= 1")

        storage_key = visual.storage_key or visual.asset_path
        return cls(
            id=visual.id,
            workspace_id=workspace_id,
            project_id=project_id,
            run_id=visual.run_id,
            media_type=MediaType.IMAGE,
            origin=MediaOrigin.GENERATED,
            storage_key=storage_key,
            mime_type=None,
            width=None,
            height=None,
            duration_seconds=None,
            source_url=None,
            metadata={
                "visual_asset_id": visual.id,
                "scene_id": visual.scene_id,
                "version": visual.version,
                "is_active": visual.is_active,
                "prompt_snapshot": visual.prompt_snapshot,
                "model_used": visual.model_used,
                "provider_type": visual.provider_type,
                "storage_provider": visual.storage_provider,
                "asset_path": visual.asset_path,
            },
            created_at=visual.created_at,
        )

    def to_json(self) -> str:
        return self.model_dump_json()
