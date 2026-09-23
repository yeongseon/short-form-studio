"""Actual factory fixture with SQL auth and owned/foreign projects."""

from collections.abc import AsyncIterator

import pytest
from creator_service.project_service import InMemoryProjectStorage, project_service
from creator_service.workspace_service import InMemoryWorkspaceStorage, workspace_service
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from shorts_api.app_factory import create_app
from shorts_api.lifecycle import shutdown_state

from tests.auth_lookup_support import AuthDatabase

ORIGIN = "https://studio.example.test"
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "x-xss-protection": "1; mode=block",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


@pytest.fixture
async def middleware_app(auth_db: AuthDatabase, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("CORS_ORIGINS", ORIGIN)
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    monkeypatch.setattr(shutdown_state, "is_shutting_down", False)
    monkeypatch.setattr(shutdown_state, "inflight_requests", 0)
    projects = InMemoryProjectStorage()
    await projects.insert_project({"title": "Owned", "workspace_id": 10})
    await projects.insert_project({"title": "Foreign", "workspace_id": 30})
    workspaces = InMemoryWorkspaceStorage()
    await workspaces.add_member(10, 7)
    await workspaces.add_member(30, 8)
    monkeypatch.setattr(project_service, "db", projects)
    monkeypatch.setattr(workspace_service, "storage", workspaces)
    return create_app()


@pytest.fixture
async def middleware_client(middleware_app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=middleware_app), base_url="http://test",
        headers={"X-API-Key": "personal-one", "Origin": ORIGIN},
    ) as client:
        yield client
