# pyright: reportMissingImports=false

"""Cross-workspace IDOR tests — verify user A (workspace 1) cannot access workspace 2 resources.

Extends test_security_boundaries.py with deeper coverage:
- Visual plan endpoints (scene CRUD)
- Script endpoints
- Storyboard endpoints
- Scene asset endpoints (image regeneration)
- Run lifecycle endpoints (extended set)
- Project CRUD
- Artifact download
- Anti-enumeration: always 404, never 403
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import pytest
from httpx import AsyncClient
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Stubs — workspace 2 objects
# ---------------------------------------------------------------------------


class StubProject(BaseModel):
    id: int
    title: str
    source_type: Literal["idea", "markdown", "url", "pasted_json"] = "idea"
    idea_brief: str | None = None
    markdown_source: str | None = None
    url_source: str | None = None
    json_script: str | None = None
    status: str = "draft"
    created_at: datetime = datetime.now(timezone.utc)
    updated_at: datetime = datetime.now(timezone.utc)
    latest_run: dict[str, int | str | None] | None = None
    workspace_id: int | None = None


class StubRun(BaseModel):
    id: int
    project_id: int
    current_stage: str = "IDEA_READY"
    status: str = "active"
    active_task_id: str | None = None
    workspace_id: int | None = None
    model_config = {"extra": "allow"}

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "current_stage": self.current_stage,
            "status": self.status,
            "active_task_id": self.active_task_id,
            "workspace_id": self.workspace_id,
        }


_WS2_PROJECT = StubProject(id=99, title="Other WS", workspace_id=2, idea_brief="theirs")
_WS2_RUN = StubRun(id=99, project_id=99, workspace_id=2)


def _patch_cross_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch services so workspace-2 objects exist but workspace-1 user can't reach them."""

    class CrossWsProjectService:
        async def get_project(
            self, project_id: int, workspace_id: int | None = None
        ) -> StubProject | None:
            if project_id == 99:
                if workspace_id is not None and workspace_id != 2:
                    return None  # workspace mismatch → triggers 404
                return _WS2_PROJECT
            return None

    class CrossWsRunService:
        async def get_run(self, run_id: int, workspace_id: int | None = None) -> StubRun | None:
            if run_id == 99:
                if workspace_id is not None and workspace_id != 2:
                    return None
                return _WS2_RUN
            return None

    monkeypatch.setattr("creator_service.project_service.project_service", CrossWsProjectService())
    monkeypatch.setattr("creator_service.run_service.run_service", CrossWsRunService())


# ---------------------------------------------------------------------------
# Visual plan endpoints — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_get_visual_plan(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.get("/api/creator/runs/99/visual-plan")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_patch_scene(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.patch(
        "/api/creator/runs/99/visual-plan/scenes/scene-1",
        json={"prompt": "hacked"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_generate_visual_plan(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.post("/api/creator/runs/99/generate-visual-plan", json={})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Script endpoints — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_get_script(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.get("/api/creator/runs/99/script")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_generate_script(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.post("/api/creator/runs/99/generate-script", json={})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Storyboard endpoints — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_get_storyboard(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.get("/api/creator/runs/99/storyboard")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Scene assets — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_regenerate_scene_image(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.post(
        "/api/creator/runs/99/scenes/scene-1/regenerate-image",
        json={},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Run lifecycle — extended cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/creator/runs/99/restart"),
        ("post", "/api/creator/runs/99/stop"),
        ("post", "/api/creator/runs/99/resume"),
        ("post", "/api/creator/runs/99/approve-script"),
        ("post", "/api/creator/runs/99/approve-visual-plan"),
        ("post", "/api/creator/runs/99/generate-script"),
        ("post", "/api/creator/runs/99/generate-visual-plan"),
        ("delete", "/api/creator/runs/99"),
    ],
)
async def test_idor_run_lifecycle_endpoints(
    method: str,
    path: str,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_cross_workspace(monkeypatch)
    client_method = getattr(client, method)
    if method == "post":
        response = await client_method(path, json={})
    else:
        response = await client_method(path)
    assert response.status_code == 404, f"{method.upper()} {path} returned {response.status_code}"


# ---------------------------------------------------------------------------
# Project endpoints — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_get_project(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.get("/api/creator/projects/99")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_idor_delete_project(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.delete("/api/creator/projects/99")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Artifact download — cross-workspace denial
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idor_artifact_download(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    _patch_cross_workspace(monkeypatch)
    r = await client.get("/api/creator/runs/99/artifacts/1/download")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Anti-enumeration: all 404, never 403
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/creator/runs/99",
        "/api/creator/runs/99/script",
        "/api/creator/runs/99/visual-plan",
        "/api/creator/runs/99/storyboard",
        "/api/creator/projects/99",
    ],
)
async def test_idor_never_returns_403(
    path: str, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Cross-workspace access must return 404, never 403 (anti-enumeration)."""
    _patch_cross_workspace(monkeypatch)
    r = await client.get(path)
    assert r.status_code == 404
    body = r.json()
    detail = body.get("detail", "")
    assert "workspace" not in detail.lower()
    assert "forbidden" not in detail.lower()
