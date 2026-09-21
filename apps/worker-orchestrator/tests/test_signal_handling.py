"""Test signal handling in Celery app."""

import signal
from unittest.mock import MagicMock, patch

import pytest

from celery_app import (
    _handle_sigint,
    _handle_sigterm,
    _previous_sigint_handler,
    _previous_sigterm_handler,
)


@pytest.fixture(autouse=True)
def reset_shutdown_state():
    """Reset shutdown state before each test."""
    import celery_app

    celery_app._SHUTDOWN_REQUESTED = False
    yield
    celery_app._SHUTDOWN_REQUESTED = False


def test_sigterm_chains_to_previous_handler():
    """Test that SIGTERM handler chains to previous handler."""
    import celery_app

    previous_handler = MagicMock()
    celery_app._previous_sigterm_handler = previous_handler
    celery_app._SHUTDOWN_REQUESTED = False

    # Simulate SIGTERM
    _handle_sigterm(signal.SIGTERM, None)

    # Verify previous handler was called
    previous_handler.assert_called_once()
    assert previous_handler.call_args[0] == (signal.SIGTERM, None)
    # Verify shutdown flag was set
    assert celery_app._SHUTDOWN_REQUESTED


def test_sigint_chains_to_previous_handler():
    """Test that SIGINT handler chains to previous handler."""
    import celery_app

    previous_handler = MagicMock()
    celery_app._previous_sigint_handler = previous_handler
    celery_app._SHUTDOWN_REQUESTED = False

    # Simulate SIGINT
    _handle_sigint(signal.SIGINT, None)

    # Verify previous handler was called
    previous_handler.assert_called_once()
    assert previous_handler.call_args[0] == (signal.SIGINT, None)
    # Verify shutdown flag was set
    assert celery_app._SHUTDOWN_REQUESTED


def test_sigterm_skips_chaining_when_none():
    """Test that SIGTERM handler doesn't crash if previous is None."""
    import celery_app

    celery_app._previous_sigterm_handler = None
    celery_app._SHUTDOWN_REQUESTED = False

    # Should not raise
    _handle_sigterm(signal.SIGTERM, None)
    assert celery_app._SHUTDOWN_REQUESTED


def test_sigint_skips_chaining_when_none():
    """Test that SIGINT handler doesn't crash if previous is None."""
    import celery_app

    celery_app._previous_sigint_handler = None
    celery_app._SHUTDOWN_REQUESTED = False

    # Should not raise
    _handle_sigint(signal.SIGINT, None)
    assert celery_app._SHUTDOWN_REQUESTED


def test_sigterm_idempotent():
    """Test that SIGTERM handler is idempotent."""
    import celery_app

    celery_app._previous_sigterm_handler = MagicMock()
    celery_app._SHUTDOWN_REQUESTED = False

    # First call
    _handle_sigterm(signal.SIGTERM, None)
    assert celery_app._SHUTDOWN_REQUESTED

    # Reset the mock
    celery_app._previous_sigterm_handler.reset_mock()

    # Second call should not chain again
    _handle_sigterm(signal.SIGTERM, None)
    celery_app._previous_sigterm_handler.assert_not_called()


def test_sigint_idempotent():
    """Test that SIGINT handler is idempotent."""
    import celery_app

    celery_app._previous_sigint_handler = MagicMock()
    celery_app._SHUTDOWN_REQUESTED = False

    # First call
    _handle_sigint(signal.SIGINT, None)
    assert celery_app._SHUTDOWN_REQUESTED

    # Reset the mock
    celery_app._previous_sigint_handler.reset_mock()

    # Second call should not chain again
    _handle_sigint(signal.SIGINT, None)
    celery_app._previous_sigint_handler.assert_not_called()
