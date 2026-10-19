import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

from celery.signals import task_failure
from tasks import generate_audio as generate_audio_module

import celery_app
from tasks import hard_timeout, runtime_topology_probe


def test_hard_timeout_request_finalizes_task_run_and_quota(monkeypatch) -> None:
    # Given a prefork parent request for a claimed production delivery.
    finalize_claimed = AsyncMock(return_value=False)
    monkeypatch.setattr(
        hard_timeout,
        "_terminal_services",
        lambda: finalize_claimed,
    )

    # When the parent observes the hard timeout after the child is killed.
    hard_timeout.finalize_hard_timeout(
        "timeout-delivery",
        "old-claim",
        103,
        2.0,
        frozenset({"RENDER_GENERATING"}),
    )

    # Then a stale timeout cannot update the run or quota after its claim CAS misses.
    finalize_claimed.assert_awaited_once_with(
        "timeout-delivery",
        "old-claim",
        ANY,
        "TIMEOUT",
        "The task exceeded its 2.0 second hard time limit",
        ANY,
        103,
        frozenset({"RENDER_GENERATING"}),
    )


def test_production_request_finalizes_positional_run_id(monkeypatch) -> None:
    # Given a hard-timeout request delivered with a positional run id.
    finalized = MagicMock()
    monkeypatch.setattr(hard_timeout.Request, "on_timeout", lambda *_args: None)
    monkeypatch.setattr(hard_timeout, "finalize_hard_timeout", finalized)
    request = object.__new__(hard_timeout.ProductionRequest)
    request.id = "positional-delivery"
    request._args = (103,)
    request._kwargs = {}
    request.worker_pid = 123
    request._task = MagicMock(
        hard_timeout_safe_failure_stages=frozenset({"SCRIPT_GENERATING"}),
    )

    # When the prefork parent observes the hard timeout.
    request.on_timeout(False, 2.0)

    # Then it finalizes the positional run before cleanup.
    finalized.assert_called_once_with(
        "positional-delivery",
        "positional-delivery:123",
        103,
        2.0,
        frozenset({"SCRIPT_GENERATING"}),
    )


def test_production_request_finalizes_keyword_run_id(monkeypatch) -> None:
    # Given a production task delivered with its run id only in kwargs.
    finalized = MagicMock()
    monkeypatch.setattr(hard_timeout.Request, "on_timeout", lambda *_args: None)
    monkeypatch.setattr(hard_timeout, "finalize_hard_timeout", finalized)
    request = object.__new__(hard_timeout.ProductionRequest)
    request.id = "keyword-delivery"
    request._args = ()
    request._kwargs = {"run_id": 104}
    request.worker_pid = 124
    request._task = MagicMock(
        hard_timeout_safe_failure_stages=frozenset({"SCRIPT_GENERATING"}),
    )

    # When the prefork parent observes the hard timeout.
    request.on_timeout(False, 3.0)

    # Then it finalizes the keyword-delivered run.
    finalized.assert_called_once_with(
        "keyword-delivery",
        "keyword-delivery:124",
        104,
        3.0,
        frozenset({"SCRIPT_GENERATING"}),
    )


def test_production_request_rejects_conflicting_or_non_integer_run_id(monkeypatch) -> None:
    # Given malformed production deliveries at the process boundary.
    finalized = MagicMock()
    monkeypatch.setattr(hard_timeout.Request, "on_timeout", lambda *_args: None)
    monkeypatch.setattr(hard_timeout, "finalize_hard_timeout", finalized)

    # When the parent handles conflicting and non-integer run ids.
    for args, kwargs in (((103,), {"run_id": 104}), ((), {"run_id": "103"})):
        request = object.__new__(hard_timeout.ProductionRequest)
        request.id = "invalid-delivery"
        request._args = args
        request._kwargs = kwargs
        request.worker_pid = 123
        request._task = MagicMock(
            hard_timeout_safe_failure_stages=frozenset({"SCRIPT_GENERATING"}),
        )
        request.on_timeout(False, 2.0)

    # Then neither malformed delivery can finalize another run.
    finalized.assert_not_called()


def test_hard_timeout_finalizes_before_releasing_blocked_resources(
    monkeypatch, tmp_path,
) -> None:
    # Given a hard-timeout request whose child completion would unblock the delivery.
    events: list[str] = []
    evidence = tmp_path / "timeout.json"
    temporary = tmp_path / "storage" / "103" / "timeout.tmp"
    temporary.parent.mkdir(parents=True)
    temporary.write_text("owned", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "child_pid": 123,
                "temporary_path": "storage/103/timeout.tmp",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKER_TOPOLOGY_EVIDENCE_DIR", str(tmp_path))
    monkeypatch.setattr(
        runtime_topology_probe.Request,
        "on_timeout",
        lambda *_args: events.append("celery-timeout"),
    )
    monkeypatch.setattr(
        runtime_topology_probe,
        "finalize_hard_timeout",
        lambda task_id, claim_token, run_id, timeout, _stages: events.append(
            f"finalized:{task_id}:{claim_token}:{run_id}:{timeout}"
        ),
    )
    monkeypatch.setattr(
        runtime_topology_probe.os,
        "killpg",
        lambda *_args: events.append("child-killed"),
    )
    request = object.__new__(runtime_topology_probe._TopologyRequest)
    request.id = "timeout-delivery"
    request._args = (103, "timeout_resources", "timeout.json", "")
    request.worker_pid = 123

    # When the prefork parent handles the hard limit.
    request.on_timeout(False, 2.0)

    # Then durable failure wins before cleanup can unblock a late success result.
    assert events == [
        "celery-timeout",
        "finalized:timeout-delivery:timeout-delivery:123:103:2.0",
        "child-killed",
    ]
    assert not temporary.exists()


def test_task_failure_signal_fences_terminal_cleanup_to_delivery_claim(monkeypatch) -> None:
    # Given a delayed failure signal carrying an old delivery's claim token.
    finalize_claimed = AsyncMock(return_value=False)
    monkeypatch.setattr(celery_app, "redis", None)
    monkeypatch.setattr(
        celery_app,
        "_terminal_failure_services",
        lambda: finalize_claimed,
    )
    sender = _Sender("runtime_topology.probe")
    sender.request.claim_token = "old-claim"

    # When the real Celery failure signal fires after a successor has claimed.
    task_failure.send(
        sender=sender,
        task_id="redelivered-task",
        exception=RuntimeError("late failure"),
    )

    # Then the old callback uses its claim fence and cannot cancel successor quota.
    finalize_claimed.assert_awaited_once_with(
        "redelivered-task",
        "old-claim",
        ANY,
        "INTERNAL",
        "The operation failed unexpectedly",
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
