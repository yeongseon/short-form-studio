"""SF-28: persist one authoritative Timeline per authorized Project, with atomic
revision checks (stale writes rejected), cross-asset reference validation, and
workspace-scoped isolation. Service + in-memory storage layer.
"""

from __future__ import annotations

import asyncio

import pytest
from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import Timeline
from creator_service.timeline_service import (
    InMemoryTimelineStorage,
    TimelineService,
)


class _FakeAssetStore:
    """Minimal MediaAssetService-shaped asset owner lookup for validation."""

    def __init__(self, assets: dict[int, tuple[int, int]]) -> None:
        # asset_id -> (workspace_id, project_id)
        self._assets = assets

    async def get_asset_owner(self, asset_id: int, workspace_id: int) -> int | None:
        entry = self._assets.get(asset_id)
        if entry is None or entry[0] != workspace_id:
            return None
        return entry[1]


def _timeline(project_id: int = 1, revision: int = 0, asset_id: int = 10) -> Timeline:
    return Timeline.model_validate(
        {
            "id": "timeline-1",
            "project_id": project_id,
            "revision": revision,
            "segments": [
                {
                    "id": "seg-1",
                    "scene_id": "scene-1",
                    "asset_id": asset_id,
                    "timeline_start_seconds": 0.0,
                    "duration_seconds": 4.0,
                }
            ],
        }
    )


def _service(assets: dict[int, tuple[int, int]] | None = None) -> TimelineService:
    store = _FakeAssetStore(assets if assets is not None else {10: (1, 1)})
    return TimelineService(InMemoryTimelineStorage(), asset_owner=store)


@pytest.mark.asyncio
async def test_first_save_round_trips_with_revision_1() -> None:
    svc = _service()
    saved = await svc.save_timeline(
        project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0
    )
    assert saved.revision == 1
    loaded = await svc.load_timeline(project_id=1, workspace_id=1)
    assert loaded is not None
    assert loaded.revision == 1
    assert loaded.id == "timeline-1"
    assert [s.id for s in loaded.segments] == ["seg-1"]


@pytest.mark.asyncio
async def test_update_with_matching_revision_increments() -> None:
    svc = _service()
    await svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0)
    saved = await svc.save_timeline(
        project_id=1, workspace_id=1, timeline=_timeline(revision=1), expected_revision=1
    )
    assert saved.revision == 2


@pytest.mark.asyncio
async def test_stale_revision_rejected() -> None:
    svc = _service()
    await svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0)
    await svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=1)
    with pytest.raises(VersionConflictError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=1
        )


@pytest.mark.asyncio
async def test_first_save_with_nonzero_expected_rejected() -> None:
    svc = _service()
    with pytest.raises(VersionConflictError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=3
        )


@pytest.mark.asyncio
async def test_concurrent_first_saves_exactly_one_wins() -> None:
    svc = _service()
    results = await asyncio.gather(
        svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0),
        svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0),
        return_exceptions=True,
    )
    successes = [r for r in results if isinstance(r, Timeline)]
    conflicts = [r for r in results if isinstance(r, VersionConflictError)]
    assert len(successes) == 1
    assert len(conflicts) == 1
    loaded = await svc.load_timeline(project_id=1, workspace_id=1)
    assert loaded is not None and loaded.revision == 1


@pytest.mark.asyncio
async def test_load_returns_none_for_workspace_mismatch() -> None:
    svc = _service()
    await svc.save_timeline(project_id=1, workspace_id=1, timeline=_timeline(), expected_revision=0)
    assert await svc.load_timeline(project_id=1, workspace_id=2) is None


@pytest.mark.asyncio
async def test_load_returns_none_when_absent() -> None:
    svc = _service()
    assert await svc.load_timeline(project_id=99, workspace_id=1) is None


@pytest.mark.asyncio
async def test_save_rejects_asset_from_other_project() -> None:
    svc = _service(assets={10: (1, 2)})  # asset belongs to project 2
    with pytest.raises(ValidationError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(asset_id=10), expected_revision=0
        )
    assert await svc.load_timeline(project_id=1, workspace_id=1) is None


@pytest.mark.asyncio
async def test_save_rejects_asset_from_other_workspace_as_missing() -> None:
    svc = _service(assets={10: (2, 1)})  # asset in workspace 2
    with pytest.raises(ValidationError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(asset_id=10), expected_revision=0
        )


@pytest.mark.asyncio
async def test_save_rejects_missing_asset() -> None:
    svc = _service(assets={})
    with pytest.raises(ValidationError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(asset_id=404), expected_revision=0
        )


@pytest.mark.asyncio
async def test_save_rejects_project_id_mismatch() -> None:
    svc = _service()
    with pytest.raises(ValidationError):
        await svc.save_timeline(
            project_id=1, workspace_id=1, timeline=_timeline(project_id=2), expected_revision=0
        )
