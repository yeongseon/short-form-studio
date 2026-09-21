"""SF-65: scene-level authorized asset search over the existing asset library.

search_scene_assets COMPOSES over MediaAssetService.list_assets — it does NOT open
a new store, index, or stock connector, and it never bypasses the library's
workspace/project scoping (so tenant isolation is inherited, not reimplemented).
It adds only discovery semantics: filter to locally reusable origins (UPLOADED /
IMPORTED / GENERATED — STOCK and EXTERNAL_URL are excluded by default since reusing
them would need an external connector), apply media constraints (type / duration /
dimensions) and an optional deterministic keyword filter, rank assets regenerated
FOR the target scene first, and surface each result's provenance so the caller
knows why an asset is reusable. Metadata is only a ranking signal AFTER authorized
candidates are listed, so a scene-id match can never override scoping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import MediaOrigin, MediaType
from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.scene_asset_search import (
    SceneAssetMatch,
    SceneAssetSearchPage,
    search_scene_assets,
)

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


_UNSET = object()


def _row(
    asset_id: int,
    *,
    workspace_id: int = 1,
    project_id: int | None = 1,
    media_type: MediaType = MediaType.IMAGE,
    origin: MediaOrigin = MediaOrigin.UPLOADED,
    storage_key: str | None | object = _UNSET,
    duration_seconds: float | None = None,
    width: int | None = None,
    height: int | None = None,
    source_url: str | None = None,
    mime_type: str | None = None,
    metadata: dict[str, object] | None = None,
    created_offset: int = 0,
) -> dict[str, object]:
    resolved_key = f"assets/{asset_id}.bin" if storage_key is _UNSET else storage_key
    return {
        "id": asset_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "run_id": None,
        "media_type": media_type.value,
        "origin": origin.value,
        "storage_key": resolved_key,
        "mime_type": mime_type,
        "width": width,
        "height": height,
        "duration_seconds": duration_seconds,
        "source_url": source_url,
        "metadata": metadata or {},
        "created_at": _NOW + timedelta(seconds=created_offset),
    }


async def _service(rows: list[dict[str, object]]) -> MediaAssetService:
    storage = InMemoryMediaAssetStorage()
    for row in rows:
        # save_asset assigns its own id; seed with explicit ids by writing directly.
        storage._assets.append(dict(row))  # noqa: SLF001 - test seed only
    return MediaAssetService(asset_storage=storage)


def _generated_for(scene_id: str, asset_id: int, **kw: object) -> dict[str, object]:
    metadata = kw.pop("metadata", None) or {
        "visual_asset_id": asset_id,
        "scene_id": scene_id,
        "version": 2,
        "model_used": "sd15",
    }
    return _row(asset_id, origin=MediaOrigin.GENERATED, metadata=metadata, **kw)


# ------------------------- tenant / project isolation -------------------------


@pytest.mark.asyncio
async def test_never_returns_assets_from_another_workspace() -> None:
    # Even when the other-workspace asset was generated for the exact scene, it is
    # never surfaced — cross-workspace search is indistinguishable from no results.
    service = await _service(
        [_generated_for("scene-A", 10, workspace_id=2)],
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert page.items == []
    assert page.total == 0


@pytest.mark.asyncio
async def test_excludes_same_workspace_assets_from_another_project() -> None:
    service = await _service(
        [
            _generated_for("scene-A", 10, project_id=1),
            _generated_for("scene-A", 11, project_id=2),
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert {m.asset.id for m in page.items} == {10}


# ------------------------- scene relevance ranking -------------------------


@pytest.mark.asyncio
async def test_ranks_assets_generated_for_this_scene_first() -> None:
    service = await _service(
        [
            _row(1, origin=MediaOrigin.UPLOADED, created_offset=100),
            _generated_for("scene-A", 2),
            _generated_for("scene-OTHER", 3),
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert page.items[0].asset.id == 2
    assert page.items[0].scene_match is True
    # the uploaded asset and the other-scene generated asset are not scene matches
    for match in page.items[1:]:
        assert match.scene_match is False


@pytest.mark.asyncio
async def test_preserves_library_order_for_non_scene_matches() -> None:
    # With no scene match, the existing uploaded-first library order is preserved.
    service = await _service(
        [
            _row(1, origin=MediaOrigin.GENERATED, metadata={"scene_id": "scene-X"}),
            _row(2, origin=MediaOrigin.UPLOADED),
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert [m.asset.id for m in page.items] == [2, 1]
    assert all(m.scene_match is False for m in page.items)


# ------------------------- reusable-origin filtering -------------------------


@pytest.mark.asyncio
async def test_excludes_stock_and_external_url_by_default() -> None:
    service = await _service(
        [
            _row(1, origin=MediaOrigin.UPLOADED),
            _row(2, origin=MediaOrigin.STOCK),
            _row(3, origin=MediaOrigin.EXTERNAL_URL, source_url="https://x/y.png"),
            _row(4, origin=MediaOrigin.IMPORTED),
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert {m.asset.id for m in page.items} == {1, 4}


@pytest.mark.asyncio
async def test_reusable_only_false_includes_stock_and_external() -> None:
    service = await _service(
        [
            _row(1, origin=MediaOrigin.UPLOADED),
            _row(2, origin=MediaOrigin.STOCK),
        ]
    )
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", reusable_only=False
    )
    assert {m.asset.id for m in page.items} == {1, 2}


@pytest.mark.asyncio
async def test_excludes_assets_without_a_local_storage_reference() -> None:
    service = await _service(
        [
            _row(1, origin=MediaOrigin.UPLOADED, storage_key=None),
            _row(2, origin=MediaOrigin.UPLOADED),
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert {m.asset.id for m in page.items} == {2}


# ------------------------- media constraints -------------------------


@pytest.mark.asyncio
async def test_filters_by_media_type() -> None:
    service = await _service(
        [
            _row(1, media_type=MediaType.IMAGE),
            _row(2, media_type=MediaType.VIDEO, duration_seconds=5.0),
        ]
    )
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", media_type=MediaType.VIDEO
    )
    assert {m.asset.id for m in page.items} == {2}


@pytest.mark.asyncio
async def test_filters_by_duration_bounds() -> None:
    service = await _service(
        [
            _row(1, media_type=MediaType.VIDEO, duration_seconds=2.0),
            _row(2, media_type=MediaType.VIDEO, duration_seconds=5.0),
            _row(3, media_type=MediaType.VIDEO, duration_seconds=12.0),
        ]
    )
    page = await search_scene_assets(
        service,
        workspace_id=1,
        project_id=1,
        scene_id="scene-A",
        media_type=MediaType.VIDEO,
        min_duration_seconds=3.0,
        max_duration_seconds=8.0,
    )
    assert {m.asset.id for m in page.items} == {2}


@pytest.mark.asyncio
async def test_duration_constrained_search_excludes_assets_without_duration() -> None:
    service = await _service(
        [
            _row(1, media_type=MediaType.VIDEO, duration_seconds=5.0),
            _row(2, media_type=MediaType.VIDEO, duration_seconds=None),
        ]
    )
    page = await search_scene_assets(
        service,
        workspace_id=1,
        project_id=1,
        scene_id="scene-A",
        media_type=MediaType.VIDEO,
        min_duration_seconds=1.0,
    )
    assert {m.asset.id for m in page.items} == {1}


@pytest.mark.asyncio
async def test_filters_by_minimum_dimensions() -> None:
    service = await _service(
        [
            _row(1, width=1080, height=1920),
            _row(2, width=640, height=480),
            _row(3, width=None, height=None),
        ]
    )
    page = await search_scene_assets(
        service,
        workspace_id=1,
        project_id=1,
        scene_id="scene-A",
        min_width=1080,
        min_height=1080,
    )
    assert {m.asset.id for m in page.items} == {1}


# ------------------------- keyword filtering -------------------------


@pytest.mark.asyncio
async def test_keyword_query_matches_all_tokens_case_insensitively() -> None:
    service = await _service(
        [
            _generated_for("scene-A", 1, metadata={"scene_id": "scene-A", "prompt_snapshot": "a rainy Tokyo street at night"}),
            _generated_for("scene-A", 2, metadata={"scene_id": "scene-A", "prompt_snapshot": "a sunny beach"}),
        ]
    )
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", query="TOKYO night"
    )
    assert {m.asset.id for m in page.items} == {1}


@pytest.mark.asyncio
async def test_blank_query_does_not_filter() -> None:
    service = await _service([_row(1), _row(2)])
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", query="   "
    )
    assert {m.asset.id for m in page.items} == {1, 2}


@pytest.mark.asyncio
async def test_non_matching_query_returns_empty() -> None:
    service = await _service(
        [_generated_for("scene-A", 1, metadata={"scene_id": "scene-A", "prompt_snapshot": "a beach"})]
    )
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", query="mountain"
    )
    assert page.items == []


# ------------------------- validation + empty results -------------------------


@pytest.mark.asyncio
async def test_empty_library_returns_an_empty_page_not_an_error() -> None:
    service = await _service([])
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    assert isinstance(page, SceneAssetSearchPage)
    assert page.items == []
    assert page.total == 0


@pytest.mark.asyncio
async def test_rejects_invalid_constraints() -> None:
    service = await _service([_row(1)])
    for bad in (
        {"min_duration_seconds": -1.0},
        {"min_duration_seconds": float("nan")},
        {"min_duration_seconds": 8.0, "max_duration_seconds": 3.0},
        {"min_width": -1},
        {"min_height": 0},
        {"limit": 0},
        {"offset": -1},
    ):
        with pytest.raises(ValidationError):
            await search_scene_assets(
                service, workspace_id=1, project_id=1, scene_id="scene-A", **bad
            )


@pytest.mark.asyncio
async def test_scene_match_beyond_the_first_candidate_page_is_still_found() -> None:
    # list_assets orders GENERATED last, so a scene-matched generated asset can
    # sort after >200 uploaded assets. All authorized candidates must be traversed
    # so the best match is never silently dropped past a fixed fetch window.
    rows = [_row(i, origin=MediaOrigin.UPLOADED, created_offset=i) for i in range(1, 202)]
    rows.append(_generated_for("scene-A", 5000))
    service = await _service(rows)
    page = await search_scene_assets(
        service, workspace_id=1, project_id=1, scene_id="scene-A", limit=1
    )
    assert page.items[0].asset.id == 5000
    assert page.items[0].scene_match is True
    assert page.total == 202


# ------------------------- provenance -------------------------


@pytest.mark.asyncio
async def test_generated_result_exposes_full_provenance() -> None:
    service = await _service(
        [
            _generated_for(
                "scene-A",
                7,
                metadata={
                    "scene_id": "scene-A",
                    "visual_asset_id": 7,
                    "version": 3,
                    "model_used": "sd15",
                    "prompt_snapshot": "a forest",
                },
            )
        ]
    )
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    match = page.items[0]
    assert isinstance(match, SceneAssetMatch)
    prov = match.provenance
    assert prov.origin == MediaOrigin.GENERATED
    assert prov.scene_id == "scene-A"
    assert prov.visual_asset_id == 7
    assert prov.version == 3
    assert prov.model_used == "sd15"
    assert match.scene_match is True


@pytest.mark.asyncio
async def test_uploaded_result_exposes_origin_without_generated_metadata() -> None:
    service = await _service([_row(3, origin=MediaOrigin.UPLOADED)])
    page = await search_scene_assets(service, workspace_id=1, project_id=1, scene_id="scene-A")
    prov = page.items[0].provenance
    assert prov.origin == MediaOrigin.UPLOADED
    assert prov.scene_id is None
    assert prov.visual_asset_id is None
    assert page.items[0].scene_match is False
