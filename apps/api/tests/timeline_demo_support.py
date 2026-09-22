from dataclasses import dataclass
from pathlib import Path

import pytest
from creator_service.media_asset_service import InMemoryMediaAssetStorage, MediaAssetService
from creator_service.object_storage import LocalStorageBackend
from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.run_service import InMemoryRunStorage, RunService
from creator_service.stage_review_service import InMemoryStageReviewStorage, StageReviewService
from creator_service.timeline_service import TimelineService
from creator_service.workspace_service import InMemoryWorkspaceStorage, WorkspaceService
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import CurrentUser, get_current_user, require_current_user
from shorts_api.routes import creator_demo_short, creator_timeline_render


@dataclass(frozen=True, slots=True)
class DemoEnvironment:
    client: AsyncClient
    runs: RunService
    projects: ProjectService
    media: MediaAssetService
    timelines: TimelineService
    reviews: StageReviewService
    dispatches: list[tuple[int, str]]
    app: FastAPI


async def environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DemoEnvironment:
    projects = ProjectService(InMemoryProjectStorage())
    runs = RunService(InMemoryRunStorage())
    media = MediaAssetService(LocalStorageBackend(str(tmp_path)), InMemoryMediaAssetStorage())
    timelines = TimelineService()
    reviews = StageReviewService(InMemoryStageReviewStorage())
    workspaces = WorkspaceService(InMemoryWorkspaceStorage())
    await workspaces.create_workspace("Test", "test", owner_id=17)
    monkeypatch.setattr("shorts_api.auth.workspace_service", workspaces)
    for module, service in (("project_service", projects), ("run_service", runs),
                            ("media_asset_service", media), ("timeline_service", timelines),
                            ("stage_review_service", reviews)):
        monkeypatch.setattr(f"creator_service.{module}.{module}", service)
        if hasattr(creator_demo_short, module):
            monkeypatch.setattr(creator_demo_short, module, service)
    app = FastAPI()
    app.include_router(creator_demo_short.router, prefix="/api/creator")
    from shorts_api.app_factory import create_app

    app.exception_handlers.update(create_app().exception_handlers)
    dispatches: list[tuple[int, str]] = []

    def dispatch_render_video(run_id: int, render_profile: str) -> str:
        dispatches.append((run_id, render_profile))
        return "sync-test-render"

    app.include_router(creator_timeline_render.router, prefix="/api/creator")
    for name, service in (("run_service", runs), ("media_asset_service", media),
                          ("timeline_service", timelines), ("stage_review_service", reviews)):
        monkeypatch.setattr(creator_timeline_render, name, service)
    monkeypatch.setattr(creator_timeline_render, "dispatch_render_video", dispatch_render_video)

    async def current_user() -> CurrentUser:
        return CurrentUser(user_id=17, workspace_id=1)

    app.dependency_overrides[require_current_user] = current_user
    app.dependency_overrides[get_current_user] = current_user
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return DemoEnvironment(client, runs, projects, media, timelines, reviews, dispatches, app)
