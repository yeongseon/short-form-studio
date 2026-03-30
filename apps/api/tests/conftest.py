"""Pytest fixtures for API tests."""
import pytest
from httpx import AsyncClient, ASGITransport
from shorts_api.main import app


@pytest.fixture
async def client():
    """AsyncClient fixture for testing FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
