from dataclasses import dataclass

import pytest
from creator_domain.models import MediaSegment, Timeline
from creator_provider.registry import ModelCatalogEntry, ProviderCategory, ProviderRegistry
from creator_service.model_catalog_service import ModelCatalogService
from creator_service.model_health_service import ModelHealthService
from creator_service.project_service import InMemoryProjectStorage, ProjectService
from creator_service.timeline_service import InMemoryTimelineStorage, TimelineService
from fastapi.routing import APIRoute
from httpx import AsyncClient
from shorts_api.auth import CurrentUser, require_workspace_access
from shorts_api.main import app


@dataclass(frozen=True, slots=True)
class AssetOwner:
    project_id: int

    async def get_asset_owner(self, asset_id: int, workspace_id: int) -> int | None:
        return self.project_id if workspace_id == 1 and asset_id == 501 else None


@pytest.fixture
def workspace_access(monkeypatch: pytest.MonkeyPatch) -> None:
    async def authorized(workspace_id: int) -> CurrentUser:
        return CurrentUser(user_id=1, workspace_id=workspace_id)

    monkeypatch.setitem(app.dependency_overrides, require_workspace_access, authorized)


@pytest.mark.asyncio
@pytest.mark.parametrize("draft_kind", ["absent", "empty", "nonempty"])
async def test_onboarding_response_tracks_persisted_timeline(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, draft_kind: str, workspace_access: None,
) -> None:
    # Given a real returning project and isolated timeline storage.
    storage = InMemoryProjectStorage()
    row = await storage.insert_project({"title": "Returning", "workspace_id": 1})
    project_id = int(row["id"])
    timelines = TimelineService(InMemoryTimelineStorage(), asset_owner=AssetOwner(project_id))
    if draft_kind != "absent":
        segments = [MediaSegment(
            id="saved-scene", scene_id="scene", asset_id=501,
            timeline_start_seconds=0, duration_seconds=5,
        )] if draft_kind == "nonempty" else []
        await timelines.save_timeline(
            project_id=project_id, workspace_id=1, expected_revision=0,
            timeline=Timeline(id="saved-draft", project_id=project_id, segments=segments),
        )
    registry = ProviderRegistry()
    registry.register_model(ModelCatalogEntry(
        "script", "openai_llm", "https://api.openai.com", ProviderCategory.LLM, is_local=False,
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name == "get_onboarding_guidance":
            namespace = route.endpoint.__globals__
            monkeypatch.setitem(namespace, "project_service", ProjectService(storage))
            monkeypatch.setitem(namespace, "timeline_service", timelines)
            monkeypatch.setitem(namespace, "get_default_registry", lambda: registry)
            monkeypatch.setitem(namespace, "list_configured_providers", lambda: ["openai"])
            monkeypatch.setitem(namespace, "_health_service", ModelHealthService())
    # When the actual HTTP onboarding endpoint is read.
    response = await client.get("/api/creator/workspaces/1/onboarding")
    # Then empty/missing timelines differ from a persisted first draft.
    assert response.status_code == 200
    body = response.json()
    assert body["flow"] == "returning"
    assert body["has_first_draft"] is (draft_kind == "nonempty")
    assert body["setup_step"] == ("complete" if draft_kind == "nonempty" else "first_draft")
    assert body["setup_status"] == ("complete" if draft_kind == "nonempty" else "ready")


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["", "/status", "/provider-config"])
async def test_model_http_surfaces_keep_configured_keys_unverified(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, surface: str,
) -> None:
    # Given real catalog/health services with an isolated remote-only registry.
    registry = ProviderRegistry()
    registry.register_model(ModelCatalogEntry(
        "script", "openai_llm", "https://custom.invalid/v1", ProviderCategory.LLM, is_local=False,
    ))
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    health = ModelHealthService()
    for route in app.routes:
        if isinstance(route, APIRoute) and route.name in {
            "list_models", "get_model_status", "get_provider_config",
        }:
            namespace = route.endpoint.__globals__
            monkeypatch.setitem(namespace, "model_catalog_service", ModelCatalogService(registry, health))
            monkeypatch.setitem(namespace, "get_default_registry", lambda: registry)
            monkeypatch.setitem(namespace, "list_configured_providers", lambda: ["openai"])
            monkeypatch.setitem(namespace, "_health_service", health)
    # When each actual HTTP surface serializes its readiness facts.
    response = await client.get(f"/api/creator/models{surface}")
    # Then the wire contract never upgrades credential presence to verified health.
    assert response.status_code == 200
    body = response.json()
    rows = body["script_models"] if surface == "" else body["providers"]
    assert rows[0]["status"] == "configured_unverified"
    if surface == "/status":
        assert rows[0]["healthy"] is False
