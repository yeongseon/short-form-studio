"""SF-65: scene-level authorized asset search over the existing asset library.

search_scene_assets COMPOSES over MediaAssetService.list_assets — it does NOT open
a new store, index, or stock connector, and it never bypasses the library's
workspace/project scoping (so tenant isolation is inherited, not reimplemented). It
adds only discovery semantics: filter to locally reusable origins (UPLOADED /
IMPORTED / GENERATED — STOCK and EXTERNAL_URL are excluded by default since reusing
them would need an external connector), apply media constraints (type / duration /
dimensions) and an optional deterministic keyword filter, rank assets regenerated
FOR the target scene first, and surface each result's provenance so the caller
knows why an asset is reusable. Metadata is only a ranking signal AFTER authorized
candidates are listed, so a scene-id match can never override scoping.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from creator_domain.exceptions import ValidationError
from creator_domain.models import MediaAsset, MediaOrigin, MediaType

from creator_service.media_asset_service import MediaAssetService

_REUSABLE_ORIGINS = frozenset(
    {MediaOrigin.UPLOADED, MediaOrigin.IMPORTED, MediaOrigin.GENERATED}
)
# Page size for traversing the authorized candidate set. list_assets orders
# GENERATED last, so a scene-matched generated asset can sort after every uploaded
# asset; the search must inspect ALL authorized candidates (not just the first
# page) or the highest-relevance match is silently dropped in large libraries.
_CANDIDATE_PAGE_SIZE = 200


@dataclass(frozen=True)
class AssetProvenance:
    origin: MediaOrigin
    scene_id: str | None = None
    visual_asset_id: int | None = None
    version: int | None = None
    model_used: str | None = None


@dataclass(frozen=True)
class SceneAssetMatch:
    asset: MediaAsset
    provenance: AssetProvenance
    scene_match: bool


@dataclass(frozen=True)
class SceneAssetSearchPage:
    items: list[SceneAssetMatch]
    total: int
    limit: int
    offset: int


def _validate(
    *,
    min_duration_seconds: float | None,
    max_duration_seconds: float | None,
    min_width: int | None,
    min_height: int | None,
    limit: int,
    offset: int,
) -> None:
    for label, value in (
        ("min_duration_seconds", min_duration_seconds),
        ("max_duration_seconds", max_duration_seconds),
    ):
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValidationError(f"{label} must be a finite, non-negative number")
    if (
        min_duration_seconds is not None
        and max_duration_seconds is not None
        and min_duration_seconds > max_duration_seconds
    ):
        raise ValidationError("min_duration_seconds must be <= max_duration_seconds")
    for label, value in (("min_width", min_width), ("min_height", min_height)):
        if value is not None and value < 1:
            raise ValidationError(f"{label} must be a positive number of pixels")
    if limit < 1:
        raise ValidationError("limit must be >= 1")
    if offset < 0:
        raise ValidationError("offset must be >= 0")


def _provenance(asset: MediaAsset, *, scene_id: str) -> tuple[AssetProvenance, bool]:
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    asset_scene = metadata.get("scene_id")
    scene_match = asset.origin == MediaOrigin.GENERATED and asset_scene == scene_id
    provenance = AssetProvenance(
        origin=asset.origin,
        scene_id=asset_scene if isinstance(asset_scene, str) else None,
        visual_asset_id=metadata.get("visual_asset_id")
        if isinstance(metadata.get("visual_asset_id"), int)
        else None,
        version=metadata.get("version") if isinstance(metadata.get("version"), int) else None,
        model_used=metadata.get("model_used")
        if isinstance(metadata.get("model_used"), str)
        else None,
    )
    return provenance, scene_match


def _searchable_text(asset: MediaAsset) -> str:
    metadata = asset.metadata if isinstance(asset.metadata, dict) else {}
    parts = [
        str(metadata.get("prompt_snapshot") or ""),
        str(metadata.get("asset_path") or ""),
        asset.storage_key or "",
        asset.source_url or "",
        asset.mime_type or "",
    ]
    return " ".join(parts).lower()


def _passes_constraints(
    asset: MediaAsset,
    *,
    min_duration_seconds: float | None,
    max_duration_seconds: float | None,
    min_width: int | None,
    min_height: int | None,
    query_tokens: list[str],
) -> bool:
    if min_duration_seconds is not None or max_duration_seconds is not None:
        if asset.duration_seconds is None:
            return False
        if min_duration_seconds is not None and asset.duration_seconds < min_duration_seconds:
            return False
        if max_duration_seconds is not None and asset.duration_seconds > max_duration_seconds:
            return False
    if min_width is not None and (asset.width is None or asset.width < min_width):
        return False
    if min_height is not None and (asset.height is None or asset.height < min_height):
        return False
    if query_tokens:
        haystack = _searchable_text(asset)
        if not all(token in haystack for token in query_tokens):
            return False
    return True


async def _list_authorized_candidates(
    service: MediaAssetService,
    *,
    workspace_id: int,
    project_id: int | None,
    media_type: MediaType | None,
) -> list[MediaAsset]:
    candidates: list[MediaAsset] = []
    offset = 0
    while True:
        page = await service.list_assets(
            workspace_id=workspace_id,
            media_type=media_type,
            project_id=project_id,
            limit=_CANDIDATE_PAGE_SIZE,
            offset=offset,
        )
        candidates.extend(page.items)
        offset += len(page.items)
        if not page.items or offset >= page.total:
            break
    return candidates


async def search_scene_assets(
    service: MediaAssetService,
    *,
    workspace_id: int,
    project_id: int | None,
    scene_id: str,
    media_type: MediaType | None = None,
    query: str | None = None,
    min_duration_seconds: float | None = None,
    max_duration_seconds: float | None = None,
    min_width: int | None = None,
    min_height: int | None = None,
    reusable_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> SceneAssetSearchPage:
    """Find authorized reusable assets for a scene, ranked scene-match first.

    Authorization/scoping is delegated to MediaAssetService.list_assets (workspace
    + project), so cross-tenant assets are never listed. Locally reusable origins
    are kept (STOCK / EXTERNAL_URL excluded unless reusable_only is False), media
    and keyword constraints are applied in memory, and generated assets whose
    provenance scene_id matches are ranked first via a stable sort that otherwise
    preserves the library ordering.
    """
    _validate(
        min_duration_seconds=min_duration_seconds,
        max_duration_seconds=max_duration_seconds,
        min_width=min_width,
        min_height=min_height,
        limit=limit,
        offset=offset,
    )
    query_tokens = query.lower().split() if query is not None else []

    candidates = await _list_authorized_candidates(
        service,
        workspace_id=workspace_id,
        project_id=project_id,
        media_type=media_type,
    )

    matches: list[SceneAssetMatch] = []
    for asset in candidates:
        # Defense in depth: the library already scopes by workspace/project, but a
        # fail-closed re-check keeps the search layer robust against a storage
        # regression that could leak a cross-tenant row.
        if asset.workspace_id != workspace_id:
            continue
        if project_id is not None and asset.project_id != project_id:
            continue
        if reusable_only and asset.origin not in _REUSABLE_ORIGINS:
            continue
        if reusable_only and not asset.storage_key:
            continue
        if not _passes_constraints(
            asset,
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            min_width=min_width,
            min_height=min_height,
            query_tokens=query_tokens,
        ):
            continue
        provenance, scene_match = _provenance(asset, scene_id=scene_id)
        matches.append(
            SceneAssetMatch(asset=asset, provenance=provenance, scene_match=scene_match)
        )

    # Stable sort on scene-match only, so the library's uploaded-first / newest
    # ordering is preserved within each group.
    ranked = sorted(matches, key=lambda m: 0 if m.scene_match else 1)
    total = len(ranked)
    window = ranked[offset : offset + limit]
    return SceneAssetSearchPage(items=window, total=total, limit=limit, offset=offset)
