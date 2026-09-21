"""SF-30 API: Timeline preview endpoint — returns the same compiled RenderPlan
final rendering consumes, so the browser preview and the render share one source.

Covers: compiled round-trip (default + selected output/encoding presets), 404
tenant isolation, 404 when no saved timeline, 400 on unknown preset, and 400 on
missing/unavailable media (compiler ValidationError).
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    EncodingProfile,
    OutputSpec,
    RenderPlan,
    RenderSegment,
    RenderSegmentKind,
    Timeline,
)
from fastapi.routing import APIRoute
from shorts_api.main import app


def _iter_api_routes(routes: Sequence[object]) -> list[APIRoute]:
    return [r for r in routes if isinstance(r, APIRoute)]


def _saved_timeline() -> Timeline:
    return Timeline.model_validate(
        {
            "id": "tl-1",
            "project_id": 1,
            "revision": 2,
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
    )


def _render_plan(output: OutputSpec, encoding: EncodingProfile) -> RenderPlan:
    return RenderPlan(
        segments=[
            RenderSegment(
                kind=RenderSegmentKind.IMAGE,
                source="workspaces/1/assets/a.png",
                timeline_start_seconds=0.0,
                duration_seconds=4.0,
            )
        ],
        output_spec=output,
        encoding_profile=encoding,
    )


class StubTimelineService:
    def __init__(self, timeline: Timeline | None) -> None:
        self._timeline = timeline

    async def load_timeline(self, *, project_id: int, workspace_id: int) -> Timeline | None:
        if workspace_id != 1:
            return None
        return self._timeline


class _CompilerSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.raise_validation = False

    async def __call__(
        self,
        timeline: Timeline,
        *,
        workspace_id: int,
        output_spec: OutputSpec,
        encoding_profile: EncodingProfile,
        asset_resolver: object,
    ) -> RenderPlan:
        self.calls.append(
            {
                "timeline": timeline,
                "workspace_id": workspace_id,
                "output_spec": output_spec,
                "encoding_profile": encoding_profile,
            }
        )
        if self.raise_validation:
            raise ValidationError("Timeline segment references an unavailable asset")
        return _render_plan(output_spec, encoding_profile)


@pytest.fixture
def stub_preview(monkeypatch: pytest.MonkeyPatch):
    from shorts_api.auth import CurrentUser, require_project_access
    from shorts_api.routes import creator_timeline

    svc = StubTimelineService(_saved_timeline())
    spy = _CompilerSpy()
    for route in _iter_api_routes(creator_timeline.router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "timeline_service", svc)
        monkeypatch.setitem(
            route.endpoint.__globals__, "compile_timeline_to_render_plan", spy
        )

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, object]:
        from fastapi import HTTPException

        if project_id != 1:
            raise HTTPException(status_code=404, detail="Project not found")
        return CurrentUser(user_id=1, workspace_id=1), object()

    app.dependency_overrides[require_project_access] = _require_project_access
    yield svc, spy
    app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_preview_returns_compiled_render_plan(client, stub_preview) -> None:
    _svc, spy = stub_preview
    res = await client.get("/api/creator/projects/1/timeline/preview")
    assert res.status_code == 200
    body = res.json()
    assert body["output_spec"]["width"] == 1080
    assert body["output_spec"]["height"] == 1920
    assert body["encoding_profile"]["name"] == "preview"
    assert len(body["segments"]) == 1
    assert body["segments"][0]["source"] == "workspaces/1/assets/a.png"
    # preview must compile the SAME saved revision the renderer would consume
    assert spy.calls[0]["timeline"].revision == 2


@pytest.mark.asyncio
async def test_preview_honors_output_and_encoding_params(client, stub_preview) -> None:
    res = await client.get(
        "/api/creator/projects/1/timeline/preview"
        "?output=short_square&encoding=high_quality"
    )
    assert res.status_code == 200
    body = res.json()
    assert body["output_spec"]["width"] == 1080
    assert body["output_spec"]["height"] == 1080
    assert body["encoding_profile"]["name"] == "high_quality"


@pytest.mark.asyncio
async def test_preview_other_workspace_project_returns_404(client, stub_preview) -> None:
    res = await client.get("/api/creator/projects/2/timeline/preview")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_preview_absent_timeline_returns_404(client, monkeypatch) -> None:
    from shorts_api.auth import CurrentUser, require_project_access
    from shorts_api.routes import creator_timeline

    svc = StubTimelineService(None)
    for route in _iter_api_routes(creator_timeline.router.routes):
        monkeypatch.setitem(route.endpoint.__globals__, "timeline_service", svc)

    async def _require_project_access(project_id: int) -> tuple[CurrentUser, object]:
        return CurrentUser(user_id=1, workspace_id=1), object()

    app.dependency_overrides[require_project_access] = _require_project_access
    try:
        res = await client.get("/api/creator/projects/1/timeline/preview")
        assert res.status_code == 404
    finally:
        app.dependency_overrides.pop(require_project_access, None)


@pytest.mark.asyncio
async def test_preview_unknown_preset_returns_400(client, stub_preview) -> None:
    res = await client.get("/api/creator/projects/1/timeline/preview?output=bogus")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_preview_unavailable_media_returns_400(client, stub_preview) -> None:
    _svc, spy = stub_preview
    spy.raise_validation = True
    res = await client.get("/api/creator/projects/1/timeline/preview")
    assert res.status_code == 400
