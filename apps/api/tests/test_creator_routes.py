"""Smoke tests for creator routes."""

from fastapi.testclient import TestClient

from shorts_api.main import app


def test_health_endpoint():
    """Test that /health endpoint returns 200."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_creator_projects_endpoint():
    """Test that GET /api/creator/projects returns 200."""
    client = TestClient(app)
    response = client.get("/api/creator/projects")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "placeholder"


def test_creator_models_endpoint():
    """Test that GET /api/creator/models returns 200."""
    client = TestClient(app)
    response = client.get("/api/creator/models")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "placeholder"
