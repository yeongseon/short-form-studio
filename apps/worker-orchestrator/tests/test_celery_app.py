"""Tests for Celery app configuration."""

import importlib
import signal
from unittest.mock import patch

import celery_app as celery_module


def test_celery_app_loads(app):
    """Test that Celery app loads correctly."""
    assert app.main == "worker-orchestrator"


def test_default_queue_is_creator(app):
    """Test that default queue is set to 'creator'."""
    assert app.conf.task_default_queue == "creator"


def test_stage_queues_defined(app):
    """Test that stage-specific queues are configured."""
    queue_names = {q.name for q in app.conf.task_queues}
    assert "creator" in queue_names
    assert "script" in queue_names
    assert "image" in queue_names
    assert "audio" in queue_names
    assert "render" in queue_names


def test_task_routing_configured(app):
    """Test that tasks route to stage-specific queues."""
    routes = app.conf.task_routes
    assert routes["tasks.generate_script.*"]["queue"] == "script"
    assert routes["tasks.generate_scene_image.*"]["queue"] == "image"
    assert routes["tasks.generate_audio.*"]["queue"] == "audio"
    assert routes["tasks.render_video.*"]["queue"] == "render"
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


def test_sigterm_registration_skips_when_signal_raises_value_error() -> None:
    with patch("signal.signal", side_effect=ValueError), patch("logging.getLogger") as get_logger:
        celery_module._register_signal_handlers()

    get_logger.return_value.debug.assert_called_once_with(
        "Skipping signal handler registration: not in main thread"
    )
