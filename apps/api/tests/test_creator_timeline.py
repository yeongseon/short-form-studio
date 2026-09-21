"""SF-28 API: per-project Timeline routes — round-trip, 404 tenant isolation,
409 stale write, 400 cross-asset rejection.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from creator_domain.exceptions import ValidationError, VersionConflictError
from creator_domain.models import Timeline
from fastapi.routing import APIRoute
from shorts_api.main import app


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [r for r in routes if isinstance(r, APIRoute)]


class StubTimelineService:
    """In-memory timeline service double honoring revision + workspace scoping."""

    def __init__(self) -> None:
        self._rows: dict[int, dict[str, object]] = {}
        self.cross_asset_projects: set[int] = set()

    async def load_timeline(self, *, project_id: int, workspace_id: int) -> Timeline | None:
        row = self._rows.get(project_id)
        if row is None or row["workspace_id"] != workspace_id:
            return None
        return row["timeline"]  # type: ignore[return-value]

    async def save_timeline(
        self,
        *,
        project_id: int,
        workspace_id: int,
        timeline: Timeline,
        expected_revision: int,
    ) -> Timeline:
        if project_id in self.cross_asset_projects:
            raise ValidationError("Timeline references unavailable asset(s)")
        row = self._rows.get(project_id)
        current = int(row["timeline"].revision) if row else 0  # type: ignore[union-attr]
        if (row is None and expected_revision != 0) or (
            row is not None and current != expected_revision
        ):
            raise VersionConflictError(project_id, expected_revision, current)
        saved = timeline.model_copy(update={"revision": expected_revision + 1})
        self._rows[project_id] = {"workspace_id": workspace_id, "timeline": saved}
        return saved


def _timeline_payload(project_id: int = 1, revision: int = 0) -> dict[str, object]:
    return {
        "id": "timeline-1",
        "project_id": project_id,
        "revision": revision,
        "segments": [
            {
                "id": "seg-1",
                "scene_id": "scene-1",
                "asset_id": 10,
                "timeline_start_seconds": 0.0,
                "duration_seconds": 4.0,
            }
        ],
    }


@pytest.fixture
def stub_timeline(monkeypatch: pytest.MonkeyPatch) -> StubTimelineService:
    from shorts_api.auth import CurrentUser, require_project_access
    from shorts_api.routes import creator_timeline

    service = StubTimelineService()
    for route in _iter_api_routes(creator_timeline.router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "timeline_service", service)

    # Only workspace 1 owns project 1; workspace 2 must get 404.
    async def _require_project_access(project_id: int) -> tuple[CurrentUser, object]:
        from fastapi import HTTPException

        if project_id != 1:
            raise HTTPException(status_code=404, detail="Project not found")
        return CurrentUser(user_id=1, workspace_id=1), object()

    app.dependency_overrides[require_project_access] = _require_project_access
    yield service
    app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_put_then_get_round_trips(client, stub_timeline: StubTimelineService) -> None:
    put = await client.put(
        "/api/creator/projects/1/timeline",
        json={"expected_revision": 0, "timeline": _timeline_payload()},
    )
    assert put.status_code == 200
    assert put.json()["revision"] == 1

    got = await client.get("/api/creator/projects/1/timeline")
    assert got.status_code == 200
    body = got.json()
    assert body["revision"] == 1
    assert body["id"] == "timeline-1"
    assert [s["id"] for s in body["segments"]] == ["seg-1"]


@pytest.mark.asyncio
async def test_get_absent_timeline_returns_404(client, stub_timeline: StubTimelineService) -> None:
    got = await client.get("/api/creator/projects/1/timeline")
    assert got.status_code == 404


@pytest.mark.asyncio
async def test_get_other_workspace_project_returns_404(
    client, stub_timeline: StubTimelineService
) -> None:
    got = await client.get("/api/creator/projects/2/timeline")
    assert got.status_code == 404


@pytest.mark.asyncio
async def test_put_other_workspace_project_returns_404(
    client, stub_timeline: StubTimelineService
) -> None:
    put = await client.put(
        "/api/creator/projects/2/timeline",
        json={"expected_revision": 0, "timeline": _timeline_payload(project_id=2)},
    )
    assert put.status_code == 404


@pytest.mark.asyncio
async def test_put_stale_revision_returns_409(
    client, stub_timeline: StubTimelineService
) -> None:
    await client.put(
        "/api/creator/projects/1/timeline",
        json={"expected_revision": 0, "timeline": _timeline_payload()},
    )
    stale = await client.put(
        "/api/creator/projects/1/timeline",
        json={"expected_revision": 0, "timeline": _timeline_payload()},
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_put_cross_asset_returns_400(
    client, stub_timeline: StubTimelineService
) -> None:
    stub_timeline.cross_asset_projects.add(1)
    put = await client.put(
        "/api/creator/projects/1/timeline",
        json={"expected_revision": 0, "timeline": _timeline_payload()},
    )
    assert put.status_code == 400
