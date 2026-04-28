"""Tests for production_checks module."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from creator_service.production_checks import (
    ProductionConfigError,
    validate_production_config,
)


def _prod_env(**overrides: str) -> dict[str, str]:
    """Return a minimal valid production environment, with optional overrides."""
    base = {
        "ENVIRONMENT": "production",
        "API_KEY": "super-secret-key-12345",
        "POSTGRES_PASSWORD": "strong-random-password",
        "DATABASE_URL": "postgresql://user:pass@db:5432/mydb",
        "CORS_ORIGINS": "https://studio.example.com",
        "REDIS_URL": "redis://redis:6379/0",
        "ARTIFACT_ROOT": "/mnt/data/artifacts",
    }
    base.update(overrides)
    return base


class TestDevelopmentMode:
    """In development mode, no checks should run."""

    def test_no_env_set(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            validate_production_config()  # should not raise

    def test_explicit_development(self) -> None:
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}, clear=True):
            validate_production_config()

    def test_staging_skips(self) -> None:
        with patch.dict(os.environ, {"ENVIRONMENT": "staging"}, clear=True):
            validate_production_config()


class TestProductionMode:
    """In production mode, missing/unsafe config must fail."""

    def test_valid_config_passes(self) -> None:
        with patch.dict(os.environ, _prod_env(), clear=True):
            validate_production_config()

    def test_missing_api_key(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(API_KEY=""), clear=True),
            pytest.raises(ProductionConfigError, match="API_KEY"),
        ):
            validate_production_config()

    def test_default_postgres_password(self) -> None:
        with (
            patch.dict(
                os.environ,
                _prod_env(POSTGRES_PASSWORD="change-me-before-use"),
                clear=True,
            ),
            pytest.raises(ProductionConfigError, match="POSTGRES_PASSWORD"),
        ):
            validate_production_config()

    def test_empty_postgres_password(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(POSTGRES_PASSWORD=""), clear=True),
            pytest.raises(ProductionConfigError, match="POSTGRES_PASSWORD"),
        ):
            validate_production_config()

    def test_missing_database_url(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(DATABASE_URL=""), clear=True),
            pytest.raises(ProductionConfigError, match="DATABASE_URL"),
        ):
            validate_production_config()

    def test_missing_cors_origins(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(CORS_ORIGINS=""), clear=True),
            pytest.raises(ProductionConfigError, match="CORS_ORIGINS"),
        ):
            validate_production_config()

    def test_wildcard_cors_origins(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(CORS_ORIGINS="*"), clear=True),
            pytest.raises(ProductionConfigError, match="wildcard"),
        ):
            validate_production_config()

    def test_missing_redis_url(self) -> None:
        with (
            patch.dict(os.environ, _prod_env(REDIS_URL=""), clear=True),
            pytest.raises(ProductionConfigError, match="REDIS_URL"),
        ):
            validate_production_config()

    def test_multiple_errors_reported(self) -> None:
        with (
            patch.dict(
                os.environ,
                _prod_env(API_KEY="", DATABASE_URL=""),
                clear=True,
            ),
            pytest.raises(ProductionConfigError) as exc_info,
        ):
            validate_production_config()
        msg = str(exc_info.value)
        assert "API_KEY" in msg
        assert "DATABASE_URL" in msg

    def test_relative_artifact_root_warns(self) -> None:
        """Relative ARTIFACT_ROOT is a warning, not an error."""
        with patch.dict(os.environ, _prod_env(ARTIFACT_ROOT="./data/artifacts"), clear=True):
            validate_production_config()  # should not raise
