"""Tests for Celery app configuration."""

import signal

import celery_app as celery_module


def test_celery_app_loads(app):
    """Test that Celery app loads correctly."""
    assert app.main == "worker-orchestrator"


def test_default_queue_is_creator(app):
    """Test that default queue is set to 'creator'."""
    assert app.conf.task_default_queue == "creator"


def test_sigterm_handler_sets_shutdown_flag() -> None:
    celery_module._SHUTDOWN_REQUESTED = False
    celery_module._handle_sigterm(signal.SIGTERM, None)
    assert celery_module._SHUTDOWN_REQUESTED is True


def test_is_shutting_down_returns_flag_state() -> None:
    celery_module._SHUTDOWN_REQUESTED = False
    assert celery_module.is_shutting_down() is False
    celery_module._SHUTDOWN_REQUESTED = True
    assert celery_module.is_shutting_down() is True
    celery_module._SHUTDOWN_REQUESTED = False
