"""Pytest fixtures for Celery app tests."""
import pytest
from celery_app import celery_app


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
