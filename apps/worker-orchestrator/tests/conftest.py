"""Pytest fixtures for Celery app tests."""

import pytest
from celery_app import celery_app
from creator_domain.models import MediaType
from creator_service.object_storage import StorageResult


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
def stub_artifact_upload(monkeypatch: pytest.MonkeyPatch):
    async def _workspace_id(_run_id: int) -> int:
        return 1

    monkeypatch.setattr("tasks.task_runner.resolve_workspace_id_from_run", _workspace_id)

    def _store_artifact_file(run_id: int, local_path: str, content_type: str):
        return StorageResult(
            key=f"{run_id}/{local_path}",
            size_bytes=0,
            content_type=content_type,
            checksum="test-checksum",
            storage_provider="local",
        )

    monkeypatch.setattr(
        "creator_service.artifact_storage_integration.store_artifact_file",
        _store_artifact_file,
    )

    async def _publish_generated_file(
        *, workspace_id: int, project_id: int, run_id: int,
        local_path: str, content_type: str, media_type: MediaType,
    ) -> StorageResult:
        _ = workspace_id, project_id, media_type
        return _store_artifact_file(run_id, local_path, content_type)

    monkeypatch.setattr(
        "creator_service.artifact_storage_integration.publish_generated_file",
        _publish_generated_file,
    )
