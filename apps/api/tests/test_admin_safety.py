"""Tests for admin safety features: cache clear allowlist and ADMIN_API_KEY validation."""

import os
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from shorts_api.main import app


@pytest.fixture
def admin_headers():
    return {
        "X-Admin-Key": "test-admin-key-long-enough",
        "X-Confirm-Action": "yes",
    }


@pytest.mark.asyncio
async def test_cache_clear_rejects_wildcard_pattern(admin_headers):
    """dry_run=False with wildcard pattern is rejected."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "test-admin-key-long-enough"}):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/admin/cache/clear?key_pattern=*&dry_run=false",
                headers=admin_headers,
            )
            assert resp.status_code == 400
            assert "allowlist" in resp.json()["detail"].lower() or "Destructive" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_cache_clear_rejects_non_allowlisted_prefix(admin_headers):
    """dry_run=False with non-allowlisted prefix is rejected."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "test-admin-key-long-enough"}):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/admin/cache/clear?key_pattern=sessions:all&dry_run=false",
                headers=admin_headers,
            )
            assert resp.status_code == 400
            assert "allowlist" in resp.json()["detail"].lower() or "Allowed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_cache_clear_allows_valid_prefix(admin_headers):
    """dry_run=False with allowlisted prefix passes validation (may fail at service layer)."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "test-admin-key-long-enough"}):
        with patch("creator_service.admin_service.admin_service.clear_cache") as mock_clear:
            mock_clear.return_value = {
                "ok": True,
                "deleted_keys": 0,
                "key_pattern": "cache:creator:test",
                "dry_run": False,
                "matched_keys": [],
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/admin/cache/clear?key_pattern=cache:creator:test&dry_run=false",
                    headers=admin_headers,
                )
                # Should pass allowlist validation (200 or service-level error, not 400)
                assert resp.status_code != 400


@pytest.mark.asyncio
async def test_cache_clear_dry_run_allows_any_pattern(admin_headers):
    """dry_run=True allows any pattern for inspection."""
    with patch.dict(os.environ, {"ADMIN_API_KEY": "test-admin-key-long-enough"}):
        with patch("creator_service.admin_service.admin_service.clear_cache") as mock_clear:
            mock_clear.return_value = {
                "ok": True,
                "deleted_keys": 0,
                "key_pattern": "*",
                "dry_run": True,
                "matched_keys": ["key1"],
            }
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/admin/cache/clear?key_pattern=*&dry_run=true",
                    headers=admin_headers,
                )
                # dry_run=True should not trigger allowlist rejection
                assert resp.status_code != 400


def test_production_checks_admin_api_key_missing():
    """Production checks fail when ADMIN_API_KEY is missing."""
    from creator_service.production_checks import (
        ProductionConfigError,
        validate_production_config,
    )

    env = {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql://user:strongpass123@db:5432/app",
        "CORS_ORIGINS": "https://studio.example.com",
        "REDIS_URL": "redis://redis:6379/0",
        "ADMIN_API_KEY": "",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ProductionConfigError, match="ADMIN_API_KEY"):
            validate_production_config(service_kind="api")


def test_production_checks_admin_api_key_too_short():
    """Production checks fail when ADMIN_API_KEY is under 16 chars."""
    from creator_service.production_checks import (
        ProductionConfigError,
        validate_production_config,
    )

    env = {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql://user:strongpass123@db:5432/app",
        "CORS_ORIGINS": "https://studio.example.com",
        "REDIS_URL": "redis://redis:6379/0",
        "ADMIN_API_KEY": "short",
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(ProductionConfigError, match="ADMIN_API_KEY"):
            validate_production_config(service_kind="api")


def test_production_checks_admin_api_key_valid():
    """Production checks pass when ADMIN_API_KEY is 16+ chars."""
    from creator_service.production_checks import validate_production_config

    env = {
        "ENVIRONMENT": "production",
        "DATABASE_URL": "postgresql://user:strongpass123@db:5432/app",
        "CORS_ORIGINS": "https://studio.example.com",
        "REDIS_URL": "redis://redis:6379/0",
        "ADMIN_API_KEY": "this-is-a-valid-admin-key-123",
    }
    with patch.dict(os.environ, env, clear=False):
        # Should not raise
        validate_production_config(service_kind="api")
