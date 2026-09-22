"""Exercise Celery's exception-catching signal boundary, not direct callbacks."""

import logging
import signal

from celery.signals import after_setup_logger, worker_process_init
import celery_app
from creator_service.logging_config import JsonFormatter
import pytest


def test_json_logging_when_celery_sends_logger_keyword() -> None:
    # Given a root logger whose process-wide state must be restored after the test.
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        # When Celery emits the real logging signal with its documented keywords.
        responses = after_setup_logger.send(
            sender=None, logger=root, loglevel=logging.INFO,
            logfile=None, format="%(message)s", colorize=False,
        )
        # Then our receiver succeeds and configures real JSON output.
        assert (celery_app.setup_celery_logger, None) in responses, responses
        assert any(isinstance(handler.formatter, JsonFormatter) for handler in root.handlers)
    finally:
        root.handlers = handlers
        root.setLevel(level)


def test_telemetry_when_worker_process_initializes(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given provider-free telemetry and restorable OS signal state.
    monkeypatch.setenv("OTEL_ENABLED", "false")
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        # When the actual Celery signal invokes its connected receivers.
        responses = worker_process_init.send(sender=None)
        # Then missing imports and other swallowed signal errors cannot pass.
        assert (celery_app.setup_worker_process_telemetry, None) in responses, responses
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
