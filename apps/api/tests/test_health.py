"""Tests for health endpoint."""
import pytest


@pytest.mark.asyncio
async def test_health_returns_ok(client):
    """Test that /health endpoint returns 200 with ok status."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
