"""Test signal handling in API lifecycle."""

import asyncio
import signal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI

from shorts_api import lifecycle


@pytest.fixture(autouse=True)
def reset_signal_handlers():
    """Reset signal handler state before each test."""
    lifecycle._previous_sigterm_handler = None
    lifecycle._previous_sigint_handler = None
    lifecycle.shutdown_state.is_shutting_down = False
    yield
    # Restore default handlers
    lifecycle._previous_sigterm_handler = None
    lifecycle._previous_sigint_handler = None
    lifecycle.shutdown_state.is_shutting_down = False


@pytest.mark.asyncio
async def test_sigterm_handler_registered():
    """Test that SIGTERM handler is registered during lifespan."""
    app = FastAPI()

    async with lifecycle.lifespan(app):
        # During lifespan, the signal should be registered
        handler = signal.signal(signal.SIGTERM, signal.SIG_DFL)
        # Restore original
        signal.signal(signal.SIGTERM, handler)
        assert handler == lifecycle._handle_sigterm


@pytest.mark.asyncio
async def test_sigint_handler_registered():
    """Test that SIGINT handler is registered during lifespan."""
    app = FastAPI()

    async with lifecycle.lifespan(app):
        # During lifespan, the signal should be registered
        handler = signal.signal(signal.SIGINT, signal.SIG_DFL)
        # Restore original
        signal.signal(signal.SIGINT, handler)
        assert handler == lifecycle._handle_sigint


@pytest.mark.asyncio
async def test_sigterm_chains_to_previous_handler():
    """Test that SIGTERM handler chains to previous handler."""
    previous_handler = MagicMock()
    lifecycle._previous_sigterm_handler = previous_handler

    # Simulate SIGTERM
    lifecycle._handle_sigterm(signal.SIGTERM, None)

    # Verify previous handler was called
    previous_handler.assert_called_once()
    assert previous_handler.call_args[0] == (signal.SIGTERM, None)
    # Verify shutdown was marked
    assert lifecycle.shutdown_state.is_shutting_down


@pytest.mark.asyncio
async def test_sigint_chains_to_previous_handler():
    """Test that SIGINT handler chains to previous handler."""
    previous_handler = MagicMock()
    lifecycle._previous_sigint_handler = previous_handler

    # Simulate SIGINT
    lifecycle._handle_sigint(signal.SIGINT, None)

    # Verify previous handler was called
    previous_handler.assert_called_once()
    assert previous_handler.call_args[0] == (signal.SIGINT, None)
    # Verify shutdown was marked
    assert lifecycle.shutdown_state.is_shutting_down


@pytest.mark.asyncio
async def test_signal_handlers_skip_registration_outside_main_thread():
    """Test that signal handler registration is skipped outside main thread."""
    app = FastAPI()

    with patch("signal.signal", side_effect=ValueError("signal only works in main thread")):
        async with lifecycle.lifespan(app):
            # Should not raise, just log debug
            pass
        # Handlers should be None due to ValueError
        assert lifecycle._previous_sigterm_handler is None
        assert lifecycle._previous_sigint_handler is None


@pytest.mark.asyncio
async def test_previous_handlers_restored_on_shutdown():
    """Test that previous handlers are restored after shutdown."""
    app = FastAPI()
    previous_sigterm = MagicMock()
    previous_sigint = MagicMock()

    with patch("signal.getsignal") as mock_getsignal:
        with patch("signal.signal") as mock_signal:
            # Mock getsignal to return our handlers
            mock_getsignal.side_effect = lambda sig: (
                previous_sigterm if sig == signal.SIGTERM else previous_sigint
            )

            async with lifecycle.lifespan(app):
                pass

            # Verify previous handlers were registered during cleanup
            calls = mock_signal.call_args_list
            # Should have registered both SIGTERM and SIGINT initially
            assert any(call[0] == (signal.SIGTERM, lifecycle._handle_sigterm) for call in calls)
            assert any(call[0] == (signal.SIGINT, lifecycle._handle_sigint) for call in calls)
            # Verify restoration to distinct previous handlers
            assert any(call[0] == (signal.SIGTERM, previous_sigterm) for call in calls), \
                "SIGTERM not restored to its distinct previous handler"
            assert any(call[0] == (signal.SIGINT, previous_sigint) for call in calls), \
                "SIGINT not restored to its distinct previous handler"
