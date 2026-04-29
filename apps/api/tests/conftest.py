"""Pytest fixtures for API tests."""

# pyright: reportMissingImports=false

from hashlib import sha256

import pytest
from fastapi.routing import APIRoute
from creator_service import db as db_module
from httpx import ASGITransport, AsyncClient
from shorts_api.main import app


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    """AsyncClient fixture for testing FastAPI app."""
    api_key = "test-api-key"
    api_key_hash = sha256(api_key.encode("utf-8")).hexdigest()

    async def fake_fetch_one(query: str, *args):
        if "FROM api_keys" in query:
            return {"user_id": 10} if args and args[0] == api_key_hash else None
        if "FROM workspace_members" in query:
            return None
        return None

    class _ProjectService:
        async def get_project(self, project_id: int):
            return type("Project", (), {"id": project_id, "workspace_id": 1})()

    monkeypatch.setattr(db_module, "fetch_one", fake_fetch_one)
    project_service = _ProjectService()
    project_service_module = __import__(
        "creator_service.project_service", fromlist=["project_service"]
    )
    monkeypatch.setattr(project_service_module, "project_service", project_service)
    for route in app.routes:
        if isinstance(route, APIRoute) and "project_service" in route.endpoint.__globals__:
            monkeypatch.setitem(route.endpoint.__globals__, "project_service", project_service)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac
