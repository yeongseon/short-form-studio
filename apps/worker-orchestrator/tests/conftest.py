"""Pytest fixtures for Celery app tests."""

from dataclasses import dataclass

import pytest
from celery_app import celery_app


@dataclass
class _MockStorageResult:
    key: str
    size_bytes: int
    content_type: str
    checksum: str
    storage_provider: str


@pytest.fixture
def celery_config():
    """Celery configuration for testing."""
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
    }


@pytest.fixture
def app(celery_config):
    """Celery app fixture with test configuration."""
    celery_app.conf.update(celery_config)
    return celery_app


@pytest.fixture(autouse=True)
def mock_store_artifact_file(monkeypatch: pytest.MonkeyPatch):
    """Prevent storage integration from reading missing local files in tests."""

    def _fake_store_artifact_file(*_args, **_kwargs) -> _MockStorageResult:
        return _MockStorageResult(
            key="tests/mock-artifact.bin",
            size_bytes=0,
            content_type="application/octet-stream",
            checksum="",
            storage_provider="local",
        )

    monkeypatch.setattr(
        "creator_service.artifact_storage_integration.store_artifact_file",
        _fake_store_artifact_file,
    )
