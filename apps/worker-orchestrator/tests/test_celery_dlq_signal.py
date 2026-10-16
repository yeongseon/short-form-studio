import json
from unittest.mock import AsyncMock, MagicMock, patch

from celery.signals import task_failure
from tasks import generate_audio as generate_audio_module

import celery_app
from tasks import hard_timeout


def test_hard_timeout_request_finalizes_task_run_and_quota(monkeypatch) -> None:
    # Given a prefork parent request for a claimed production delivery.
    mark_failed = AsyncMock()
    cancel_owned = AsyncMock()
    get_run = AsyncMock(return_value={"current_stage": "RENDER_GENERATING", "status": "running"})
    update_run = AsyncMock(return_value=(True, {"status": "failed"}))
    monkeypatch.setattr(
        hard_timeout,
        "_terminal_services",
        lambda: (mark_failed, cancel_owned, get_run, update_run),
    )

    # When the parent observes the hard timeout after the child is killed.
    hard_timeout.finalize_hard_timeout("timeout-delivery", 103, 2.0)

    # Then durable task/run ownership and quota are finalized outside the dead child.
    mark_failed.assert_awaited_once_with(
        "timeout-delivery",
        "TIMEOUT",
        "The task exceeded its 2.0 second hard time limit",
    )
    cancel_owned.assert_awaited_once_with("timeout-delivery")
    update_run.assert_awaited_once_with(
        103,
        {"current_stage": "FAILED", "status": "failed"},
        expected_stages=frozenset({"RENDER_GENERATING"}),
        rejected_statuses=frozenset({"failed", "cancelled", "completed"}),
    )


class _Sender:
    def __init__(self, name: str, retries: int = 0, max_retries: int = 0) -> None:
        self.name = name
        self.max_retries = max_retries
        self.request = MagicMock()
        self.request.retries = retries


def test_task_failure_signal_writes_structured_dlq_entry(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = mock_client

    sender = _Sender("tasks.generate_script")
    task_failure.send(
        sender=sender,
        task_id="task-123",
        exception=RuntimeError("boom"),
        args=("topic", 2),
        kwargs={"language": "en"},
    )

    mock_client.lpush.assert_called_once()
    mock_client.ltrim.assert_called_once_with("dlq:creator", 0, celery_app.dlq_max_size - 1)

    payload = json.loads(mock_client.lpush.call_args.args[1])
    assert payload["task_id"] == "task-123"
    assert payload["task_name"] == "tasks.generate_script"
    assert payload["args"] == ["topic", 2]
    assert payload["kwargs"] == {"language": "en"}
    assert payload["exception"] == "The operation failed unexpectedly"
    assert payload["failure"]["code"] == "INTERNAL"
    assert isinstance(payload["timestamp"], str)
    assert payload["timestamp"]


def test_task_failure_signal_handles_redis_connection_error_gracefully(monkeypatch, tmp_path):
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(tmp_path / "dlq_fallback.jsonl"))
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.side_effect = ConnectionError("redis unavailable")

    with patch("celery_app.logging.getLogger") as get_logger:
        sender = _Sender("tasks.generate_script")
        task_failure.send(
            sender=sender,
            task_id="task-connection-error",
            exception=RuntimeError("boom"),
            args=("topic",),
            kwargs={"language": "en"},
        )

    fallback_path = tmp_path / "dlq_fallback.jsonl"
    assert fallback_path.exists()

    payload = json.loads(fallback_path.read_text(encoding="utf-8").strip())
    assert payload["task_id"] == "task-connection-error"
    assert payload["task_name"] == "tasks.generate_script"
    assert payload["kwargs"] == {"language": "en"}
    assert payload["exception"] == "The operation failed unexpectedly"
    assert payload["failure"]["code"] == "INTERNAL"

    logger = get_logger.return_value
    logger.error.assert_called()


def test_task_failure_signal_skips_dlq_for_retriable_attempt(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = mock_client

    sender = _Sender("tasks.generate_script", retries=0, max_retries=3)
    task_failure.send(
        sender=sender,
        task_id="task-retry-1",
        exception=generate_audio_module.ProviderTimeoutError("retryable"),
        args=("topic",),
        kwargs={"language": "en"},
    )

    mock_client.lpush.assert_not_called()


def test_task_failure_signal_records_nonretryable_on_first_attempt(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = mock_client

    sender = _Sender("tasks.generate_script", retries=0, max_retries=3)
    task_failure.send(
        sender=sender,
        task_id="task-nonretryable-first-attempt",
        exception=RuntimeError("not retryable"),
        args=("topic",),
        kwargs={"language": "en"},
    )

    mock_client.lpush.assert_called_once()


def test_task_failure_signal_skips_dlq_for_rate_limit_with_retries(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = mock_client

    sender = _Sender("tasks.generate_script", retries=1, max_retries=3)
    task_failure.send(
        sender=sender,
        task_id="task-rate-limit-retry-2",
        exception=generate_audio_module.RateLimitError("retryable"),
        args=("topic",),
        kwargs={"language": "en"},
    )

    mock_client.lpush.assert_not_called()


def test_task_failure_signal_records_dlq_after_retries_exhausted(monkeypatch):
    mock_client = MagicMock()
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = mock_client

    sender = _Sender("tasks.generate_script", retries=3, max_retries=3)
    task_failure.send(
        sender=sender,
        task_id="task-retry-exhausted",
        exception=RuntimeError("terminal"),
        args=("topic",),
        kwargs={"language": "en"},
    )

    mock_client.lpush.assert_called_once()
