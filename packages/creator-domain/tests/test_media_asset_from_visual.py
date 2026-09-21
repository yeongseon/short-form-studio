from __future__ import annotations

from datetime import datetime, timezone

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType, VisualAsset


def _ts() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _visual_asset(**overrides: object) -> VisualAsset:
    payload: dict[str, object] = {
        "id": 7,
        "run_id": 3,
        "scene_id": "scene-2",
        "version": 4,
        "asset_path": "data/artifacts/3/visual/scene-2.png",
        "prompt_snapshot": "a blue sky",
        "model_used": "sd15",
        "provider_type": "stable-diffusion",
        "storage_provider": "local",
        "storage_key": "3/visual/scene-2.png",
        "is_active": True,
        "created_at": _ts(),
    }
    payload.update(overrides)
    return VisualAsset.model_validate(payload)


def test_from_visual_asset_maps_core_fields() -> None:
    va = _visual_asset()

    asset = MediaAsset.from_visual_asset(va, workspace_id=11)

    assert isinstance(asset, MediaAsset)
    assert asset.workspace_id == 11
    assert asset.run_id == 3
    assert asset.media_type is MediaType.IMAGE
    assert asset.origin is MediaOrigin.GENERATED
    assert asset.storage_key == "3/visual/scene-2.png"
    assert asset.created_at == _ts()


def test_from_visual_asset_preserves_scene_selection_and_version() -> None:
    va = _visual_asset(scene_id="scene-5", version=9, is_active=False)

    asset = MediaAsset.from_visual_asset(va, workspace_id=1)

    meta = asset.metadata
    assert meta["scene_id"] == "scene-5"
    assert meta["version"] == 9
    assert meta["is_active"] is False


def test_from_visual_asset_preserves_provenance() -> None:
    va = _visual_asset()

    meta = MediaAsset.from_visual_asset(va, workspace_id=1).metadata

    assert meta["prompt_snapshot"] == "a blue sky"
    assert meta["model_used"] == "sd15"
    assert meta["provider_type"] == "stable-diffusion"
    assert meta["storage_provider"] == "local"
    # Preserve the original VisualAsset identity so records are not duplicated.
    assert meta["visual_asset_id"] == 7


def test_from_visual_asset_falls_back_to_asset_path_when_no_storage_key() -> None:
    va = _visual_asset(storage_key=None)

    asset = MediaAsset.from_visual_asset(va, workspace_id=1)

    assert asset.storage_key == "data/artifacts/3/visual/scene-2.png"


def test_from_visual_asset_carries_optional_project_id() -> None:
    va = _visual_asset()

    asset = MediaAsset.from_visual_asset(va, workspace_id=1, project_id=42)

    assert asset.project_id == 42


def test_from_visual_asset_requires_positive_workspace() -> None:
    va = _visual_asset()

    with pytest.raises(ValueError):
        MediaAsset.from_visual_asset(va, workspace_id=0)


def test_from_visual_asset_result_is_valid_media_asset_json() -> None:
    va = _visual_asset()

    asset = MediaAsset.from_visual_asset(va, workspace_id=1)
    restored = MediaAsset.model_validate_json(asset.to_json())

    assert restored == asset


def test_from_visual_asset_does_not_lose_scene_active_flag_default() -> None:
    # An active VisualAsset must remain discoverable as active in metadata.
    va = _visual_asset(is_active=True)

    asset = MediaAsset.from_visual_asset(va, workspace_id=1)

    assert asset.metadata["is_active"] is True
