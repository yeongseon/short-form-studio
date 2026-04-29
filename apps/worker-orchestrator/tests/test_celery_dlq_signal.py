import json
from types import SimpleNamespace

from celery.signals import task_failure

import celery_app


class _FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, list[str]] = {}

    def lpush(self, key: str, value: str) -> None:
        self.store.setdefault(key, []).insert(0, value)

    def ltrim(self, key: str, start: int, end: int) -> None:
        values = self.store.get(key, [])
        self.store[key] = values[start : end + 1]


class _Sender:
    def __init__(self, name: str) -> None:
        self.name = name


def test_task_failure_signal_writes_structured_dlq_entry(monkeypatch):
    # This is a unit test for the task_failure signal handler in isolation.
    # End-to-end failure behavior requires an integration test with live Redis and a Celery worker.
    fake_client = _FakeRedisClient()
    fake_redis = SimpleNamespace(
        Redis=SimpleNamespace(from_url=lambda _url: fake_client),
    )
    monkeypatch.setattr(celery_app, "redis", fake_redis)

    sender = _Sender("tasks.generate_script")
    task_failure.send(
        sender=sender,
        task_id="task-123",
        exception=RuntimeError("boom"),
        args=("topic", 2),
        kwargs={"language": "en"},
    )

    dlq_values = fake_client.store.get("dlq:creator", [])
    assert len(dlq_values) == 1

    payload = json.loads(dlq_values[0])
    assert payload["task_id"] == "task-123"
    assert payload["task_name"] == "tasks.generate_script"
    assert payload["args"] == ["topic", 2]
    assert payload["kwargs"] == {"language": "en"}
    assert payload["exception"] == "RuntimeError('boom')"
    assert isinstance(payload["timestamp"], str)
    assert payload["timestamp"]
