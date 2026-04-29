"""Tests for security headers middleware."""

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_security_headers_present_in_production(client):
    """Test that security headers are present when ENVIRONMENT=production."""
    with patch("shorts_api.main._is_production", True):
        response = await client.get("/healthz")

        assert response.status_code == 200
        # Check for presence of all security headers
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert (
            response.headers.get("Strict-Transport-Security")
            == "max-age=31536000; includeSubDomains"
        )
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert (
            response.headers.get("Permissions-Policy") == "camera=(), microphone=(), geolocation=()"
        )


@pytest.mark.asyncio
async def test_security_headers_absent_in_development(client):
    """Test that security headers are NOT present when ENVIRONMENT=development."""
    with patch("shorts_api.main._is_production", False):
        response = await client.get("/healthz")

        assert response.status_code == 200
        # Check that security headers are NOT present
        assert "X-Content-Type-Options" not in response.headers
        assert "X-Frame-Options" not in response.headers
        assert "X-XSS-Protection" not in response.headers
        assert "Strict-Transport-Security" not in response.headers
        assert "Referrer-Policy" not in response.headers
        assert "Permissions-Policy" not in response.headers
