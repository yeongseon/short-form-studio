"""Tests for authentication on admin and artifact endpoints."""

import pytest
from fastapi.testclient import TestClient

from shorts_api.main import app


@pytest.fixture
def unauthenticated_client():
    """Test client without authentication headers."""
    return TestClient(app)


class TestSettingsEndpoint:
    """Tests for /api/creator/settings/api-keys endpoint authentication."""
    
    def test_list_api_keys_requires_auth(self, unauthenticated_client):
        """Test that list_api_keys returns 401 when not authenticated."""
        response = unauthenticated_client.get("/api/creator/settings/api-keys")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


class TestModelEndpoints:
    """Tests for /api/creator/models endpoints authentication."""
    
    def test_list_models_requires_auth(self, unauthenticated_client):
        """Test that list_models returns 401 when not authenticated."""
        response = unauthenticated_client.get("/api/creator/models")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    
    def test_get_model_status_requires_auth(self, unauthenticated_client):
        """Test that get_model_status returns 401 when not authenticated."""
        response = unauthenticated_client.get("/api/creator/models/status")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"


class TestArtifactEndpoints:
    """Tests for artifact endpoints authentication."""
    
    def test_serve_artifact_requires_auth(self, unauthenticated_client):
        """Test that serve_artifact returns 401 when not authenticated."""
        response = unauthenticated_client.get("/artifacts/test/artifact.txt")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
    
    def test_serve_local_artifact_file_requires_auth(self, unauthenticated_client):
        """Test that serve_local_artifact_file returns 401 when not authenticated."""
        response = unauthenticated_client.get("/api/artifacts/files/test.txt")
        assert response.status_code == 401, f"Expected 401, got {response.status_code}: {response.text}"
