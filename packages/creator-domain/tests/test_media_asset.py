from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from creator_domain.models import MediaAsset, MediaOrigin, MediaType
from pydantic import ValidationError


def _ts() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": 1,
        "workspace_id": 1,
        "media_type": MediaType.IMAGE,
        "origin": MediaOrigin.GENERATED,
        "created_at": _ts(),
    }
    base.update(overrides)
    return base


# --- SF-02: MediaType / MediaOrigin -----------------------------------------


def test_media_type_has_expected_members() -> None:
    assert {m.value for m in MediaType} == {"IMAGE", "VIDEO", "AUDIO", "LOGO", "GRAPHIC"}


def test_media_origin_has_expected_members() -> None:
    assert {m.value for m in MediaOrigin} == {
        "GENERATED",
        "UPLOADED",
        "EXTERNAL_URL",
        "STOCK",
        "IMPORTED",
    }


def test_media_type_is_str_enum() -> None:
    assert MediaType.IMAGE == "IMAGE"
    assert str(MediaType.VIDEO) == "VIDEO"


def test_media_origin_is_str_enum() -> None:
    assert MediaOrigin.UPLOADED == "UPLOADED"
    assert str(MediaOrigin.STOCK) == "STOCK"


# --- SF-01: MediaAsset core contract ----------------------------------------


def test_media_asset_minimal_valid_payload() -> None:
    asset = MediaAsset.model_validate(_payload())

    assert asset.id == 1
    assert asset.workspace_id == 1
    assert asset.media_type is MediaType.IMAGE
    assert asset.origin is MediaOrigin.GENERATED
    assert asset.project_id is None
    assert asset.run_id is None
    assert asset.storage_key is None
    assert asset.mime_type is None
    assert asset.width is None
    assert asset.height is None
    assert asset.duration_seconds is None
    assert asset.source_url is None
    assert asset.metadata == {}


def test_media_asset_coerces_valid_enum_strings() -> None:
    asset = MediaAsset.model_validate(_payload(media_type="VIDEO", origin="UPLOADED"))

    assert asset.media_type is MediaType.VIDEO
    assert asset.origin is MediaOrigin.UPLOADED


def test_media_asset_rejects_invalid_media_type() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(media_type="MOVIE"))


def test_media_asset_rejects_invalid_origin() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(origin="SCRAPED"))


def test_media_asset_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(unexpected="x"))


def test_media_asset_requires_positive_ids() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(id=0))
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(workspace_id=0))


def test_media_asset_rejects_non_positive_optional_ids() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(project_id=0))
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(run_id=0))


def test_media_asset_accepts_optional_associations() -> None:
    asset = MediaAsset.model_validate(_payload(project_id=5, run_id=7))

    assert asset.project_id == 5
    assert asset.run_id == 7


def test_media_asset_rejects_negative_dimensions() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(width=-1))
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(height=-1))


def test_media_asset_rejects_negative_duration() -> None:
    with pytest.raises(ValidationError):
        MediaAsset.model_validate(_payload(duration_seconds=-0.5))


def test_media_asset_allows_no_short_only_duration_cap() -> None:
    # A generic media core must not bake in a short-only duration ceiling.
    asset = MediaAsset.model_validate(_payload(duration_seconds=1800.0))

    assert asset.duration_seconds == 1800.0


def test_media_asset_accepts_video_upload_with_probed_metadata() -> None:
    asset = MediaAsset.model_validate(
        _payload(
            media_type="VIDEO",
            origin="UPLOADED",
            project_id=3,
            storage_key="ws/1/proj/3/video.mp4",
            mime_type="video/mp4",
            width=1080,
            height=1920,
            duration_seconds=42.5,
            metadata={"size_bytes": 123456},
        )
    )

    assert asset.storage_key == "ws/1/proj/3/video.mp4"
    assert asset.mime_type == "video/mp4"
    assert asset.width == 1080
    assert asset.height == 1920
    assert asset.duration_seconds == 42.5
    assert asset.metadata == {"size_bytes": 123456}


def test_media_asset_round_trips_via_json() -> None:
    asset = MediaAsset.model_validate(_payload(source_url="https://example.com/x.png"))
    restored = MediaAsset.model_validate_json(asset.to_json())

    assert restored == asset


def test_media_asset_from_dict_matches_validate() -> None:
    payload = _payload()
    assert MediaAsset.from_dict(payload) == MediaAsset.model_validate(payload)


def test_media_asset_from_row_drops_unknown_db_columns() -> None:
    asset = MediaAsset.from_row(
        {
            **_payload(storage_key="k"),
            "internal_db_only": "ignored",
            "another": 123,
        }
    )

    assert asset.storage_key == "k"
    assert asset.media_type is MediaType.IMAGE
