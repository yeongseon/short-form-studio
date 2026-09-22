"""DLQ wire/file boundaries must never stringify unsupported input."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from creator_provider.exceptions import ProviderAuthError

import celery_app


class SecretObject:
    def __str__(self) -> str:
        return "synthetic-object-private-value"

    def __repr__(self) -> str:
        return "synthetic-object-private-value"


@pytest.mark.parametrize("fallback", [False, True])
def test_dlq_serializes_only_safe_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fallback: bool
) -> None:
    # Given: synthetic secrets in keys, objects, and an upstream auth failure.
    client = MagicMock()
    backend = MagicMock()
    backend.Redis.from_url.return_value = client
    monkeypatch.setattr(celery_app, "redis", None if fallback else backend)
    destination = tmp_path / "failures.jsonl"
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(destination))
    key = "sk-syntheticKey123456789"
    raw = "synthetic-unstructured-upstream-body"

    # When: the real writer serializes to Redis or the fallback file.
    celery_app._record_failed_task_to_dlq(
        task_id="task-safe", task_name="generate_script", args=(SecretObject(),),
        kwargs={key: "value", "safe": {"/home/synthetic/private": SecretObject()}},
        exception=ProviderAuthError(raw),
    )
    serialized = destination.read_text() if fallback else client.lpush.call_args.args[1]
    payload = json.loads(serialized)

    # Then: static root cause survives; no key, object representation, or raw message does.
    for secret in (key, raw, "/home/synthetic/private", "synthetic-object-private-value"):
        assert secret not in serialized
    assert payload["failure"]["code"] == "PROVIDER_AUTH"
    assert payload["failure"]["retryable"] is False
    assert payload["exception"] == payload["failure"]["message"]
    assert payload["args"] == ["<unsupported>"]
    assert payload["task_id"] == "task-safe"


@pytest.mark.parametrize(
    "value", [SecretObject(), b"synthetic-bytes", {1, 2}, float("nan"), float("inf"), 10**5000],
    ids=["object", "bytes", "set", "nan", "infinity", "huge-integer"],
)
def test_sanitizer_returns_strict_json_for_unsupported_values(value: object) -> None:
    # Given / When: arbitrary input crosses the sanitizer, without a JSON default hook.
    sanitized = celery_app._sanitize_for_dlq(value)
    serialized = json.dumps(sanitized, allow_nan=False)
    # Then: unsupported data has an opaque representation, never __str__/__repr__.
    assert json.loads(serialized) == "<unsupported>"


def test_sanitizer_bounds_keys_containers_and_cycles() -> None:
    # Given: a cycle, wide dictionaries, and oversized keys/values.
    cycle: list[object] = []
    cycle.append(cycle)
    raw = {f"field-{i}": "x" * 2000 for i in range(100)}
    # When
    sanitized = celery_app._sanitize_for_dlq({"wide": raw, "x" * 2000: cycle})
    # Then
    assert isinstance(sanitized, dict)
    wide = sanitized["wide"]
    assert isinstance(wide, dict)
    assert len(wide) <= 50
    assert all(len(key) <= 1024 for key in sanitized)
    assert all(isinstance(value, str) and len(value) <= 1024 for value in wide.values())
    assert "<nested>" in json.dumps(sanitized)


def test_sanitizer_does_not_stringify_object_keys() -> None:
    # Given / When
    sanitized = celery_app._sanitize_for_dlq({SecretObject(): "private", "run_id": 42})
    serialized = json.dumps(sanitized)
    # Then
    assert "synthetic-object-private-value" not in serialized
    assert "private" not in serialized
    assert json.loads(serialized)["run_id"] == 42


def test_dlq_connection_failure_logs_no_raw_exception(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Given: a transport failure containing an unstructured synthetic secret.
    backend = MagicMock()
    backend.Redis.from_url.side_effect = ConnectionError("synthetic-redis-private-value")
    monkeypatch.setattr(celery_app, "redis", backend)
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(tmp_path / "dlq.jsonl"))
    # When
    celery_app._record_failed_task_to_dlq("task-safe", "generate_script", (), {}, RuntimeError("raw"))
    # Then
    assert "DLQ Redis write failure" in caplog.text
    assert "synthetic-redis-private-value" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_fallback_write_failure_logs_only_static_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # Given: the fallback path is a directory, causing a real OSError with a private path.
    monkeypatch.setattr(celery_app, "redis", None)
    monkeypatch.setattr(celery_app, "dlq_fallback_path", str(tmp_path))
    # When
    celery_app._record_failed_task_to_dlq("task-safe", "generate_script", (), {}, RuntimeError("raw"))
    # Then
    assert "fallback file write also failed" in caplog.text
    assert str(tmp_path) not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
