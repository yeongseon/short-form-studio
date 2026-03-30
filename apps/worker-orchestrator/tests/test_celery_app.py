"""Tests for Celery app configuration."""


def test_celery_app_loads(app):
    """Test that Celery app loads correctly."""
    assert app.main == "worker-orchestrator"


def test_default_queue_is_creator(app):
    """Test that default queue is set to 'creator'."""
    assert app.conf.task_default_queue == "creator"
