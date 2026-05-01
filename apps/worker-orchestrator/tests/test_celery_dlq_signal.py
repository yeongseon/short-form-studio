import json
from unittest.mock import MagicMock, patch

import celery_app
from celery.signals import task_failure


class _Sender:
    def __init__(self, name: str) -> None:
        self.name = name


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
    assert payload["exception"] == "RuntimeError('boom')"
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
    assert "boom" in payload["exception"]

    logger = get_logger.return_value
    logger.error.assert_called()
