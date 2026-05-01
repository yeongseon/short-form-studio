# pyright: reportMissingImports=false
"""Pytest fixtures for API tests."""

import hashlib
from importlib import import_module

import pytest
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import get_current_user


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch):
    """AsyncClient fixture for testing FastAPI app."""
    api_key = "test-api-key"
    expected_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    async def _fetch_one_stub(query: str, *args: object) -> dict[str, object] | None:
        if "FROM api_keys" in query:
            key_hash = args[0] if args else None
            if key_hash == expected_hash:
                return {"user_id": 1}
            return None
        if "FROM workspace_members" in query:
            user_id = args[0] if args else None
            if user_id == 1:
                return {"workspace_id": 1, "workspace_name": "workspace-1"}
            return None
        return None

    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
    monkeypatch.setattr("shorts_api.auth.fetch_one", _fetch_one_stub)

    class _StubProject:
        workspace_id = 1
        title = ""
        idea_brief = ""

    async def _stub_get_project(_project_id: int):
        return _StubProject()

    async def _allow_quota(_workspace_id: int, operation_type: str):
        _ = operation_type
        return True, None

    async def _noop_reservation(_workspace_id: int, operation_type: str, units: int = 1) -> None:
        _ = (operation_type, units)

    monkeypatch.setattr(
        "creator_service.project_service.project_service.get_project", _stub_get_project
    )
    monkeypatch.setattr("creator_service.usage_service.check_workspace_quota", _allow_quota)
    monkeypatch.setattr(
        "creator_service.usage_service.cancel_workspace_quota_reservation", _noop_reservation
    )

    async def _test_user_context() -> dict[str, str | int]:
        return {
            "user_id": 1,
            "auth_provider": "api_key",
            "auth_subject": "test",
            "workspace_id": 1,
        }

    main_module = import_module("shorts_api.main")
    app = main_module.app
    app.dependency_overrides[get_current_user] = _test_user_context
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": api_key},
    ) as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
