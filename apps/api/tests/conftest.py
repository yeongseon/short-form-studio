"""Pytest fixtures for API tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from shorts_api.auth import get_current_user
from shorts_api.main import app


@pytest.fixture
async def client():
    """AsyncClient fixture for testing FastAPI app."""

    async def _test_user_context() -> dict[str, str | int]:
        return {
            "user_id": 1,
            "auth_provider": "api_key",
            "auth_subject": "test",
            "workspace_id": 1,
        }

    app.dependency_overrides[get_current_user] = _test_user_context
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_current_user, None)
