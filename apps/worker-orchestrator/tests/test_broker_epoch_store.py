from datetime import datetime, timezone
from unittest.mock import MagicMock

import celery_app


def test_broker_epoch_is_stable_until_redis_storage_is_replaced(monkeypatch) -> None:
    # Given
    client = MagicMock()
    client.set.return_value = True
    client.get.return_value = b"epoch-a|2026-10-16T00:00:00+00:00"
    monkeypatch.setattr(celery_app, "redis", MagicMock())
    celery_app.redis.Redis.from_url.return_value = client

    # When
    first = celery_app.ensure_broker_epoch()
    second = celery_app.ensure_broker_epoch()

    # Then
    assert first == second
    assert first.epoch == "epoch-a"
    assert first.started_at == datetime(2026, 10, 16, tzinfo=timezone.utc)
    assert client.set.call_args.args[0] == "queue:recovery_epoch"
    assert client.set.call_args.kwargs == {"nx": True}


def test_broker_epoch_retries_transient_redis_failure(monkeypatch) -> None:
    # Given
    client = MagicMock()
    client.set.side_effect = [ConnectionError("transient"), True]
    client.get.return_value = b"epoch-a|2026-10-16T00:00:00+00:00"
    redis_module = MagicMock()
    redis_module.Redis.from_url.return_value = client
    redis_module.exceptions.RedisError = ConnectionError
    monkeypatch.setattr(celery_app, "redis", redis_module)
    monkeypatch.setattr(celery_app.time, "sleep", MagicMock())

    # When
    snapshot = celery_app.ensure_broker_epoch()

    # Then
    assert snapshot.epoch == "epoch-a"
    assert client.set.call_count == 2
    celery_app.time.sleep.assert_called_once_with(0.05)
