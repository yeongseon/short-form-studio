"""Typed failures survive actual generation tasks, retries, and durable summaries."""

from unittest.mock import Mock

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from creator_provider.exceptions import (
    ProviderAuthError, ProviderError, ProviderTimeoutError, ProviderValidationError, RateLimitError,
)
from worker_loop import run_in_worker_loop

from .provider_boundary_support import GenerationCase, generation_case as generation_case
from .terminal_postgres_support import terminal_pool as terminal_pool
from .terminal_validation_support import runner_case as runner_case


class VendorAuthError(ProviderAuthError):
    """An adapter-specific subtype must also survive the boundary."""

    credential_name = "offline-key"


class VendorRateLimitError(RateLimitError):
    retry_after = 73


class VendorTimeoutError(ProviderTimeoutError):
    timeout_seconds = 17


@pytest.mark.parametrize("error_type,code", [
    (ProviderAuthError, "PROVIDER_AUTH"), (VendorAuthError, "PROVIDER_AUTH"),
    (ProviderValidationError, "VALIDATION"), (ProviderError, "UNAVAILABLE"),
    (ProviderTimeoutError, "UNAVAILABLE"), (RateLimitError, "QUOTA"),
    (VendorTimeoutError, "UNAVAILABLE"), (VendorRateLimitError, "QUOTA"),
])
def test_typed_failure_keeps_identity_and_category(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch, error_type: type[ProviderError], code: str,
) -> None:
    # Given a typed failure whose text would fool legacy rate/parse heuristics.
    case = generation_case
    error = error_type("invalid 429 svg token=synthetic-private-value https://secret.invalid/private")
    case.provider.generate.side_effect = error
    case.provider.transcribe.side_effect = error
    retry = Mock(wraps=case.task.retry)
    monkeypatch.setattr(case.task, "retry", retry)
    case.task.push_request(id="provider-boundary", args=case.args, kwargs={}, retries=case.task.max_retries)
    try:
        # When the actual task and runner consume the provider failure.
        with pytest.raises(ProviderError) as raised:
            case.task.run(*case.args)
    finally:
        case.task.pop_request()
    # Then identity and safe durable category survive, with no extra provider calls.
    assert raised.value is error
    assert case.provider.generate.await_count + case.provider.transcribe.await_count == 1
    case.usage.assert_not_awaited()
    tracked = run_in_worker_loop(case.runner.tracking.list_run_tasks(case.runner.run_id))[0]
    assert (tracked.status, tracked.error_code) == ("failed", code)
    assert "synthetic-private-value" not in (tracked.error_message or "")
    assert "secret.invalid" not in (tracked.error_message or "")
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == ("FAILED", "failed")
    if issubclass(error_type, (ProviderTimeoutError, RateLimitError)):
        retry.assert_called_once()
        assert retry.call_args.kwargs["exc"] is error
    else:
        retry.assert_not_called()


@pytest.mark.parametrize("error_type,code", [
    (ProviderTimeoutError, "UNAVAILABLE"), (RateLimitError, "QUOTA"),
    (VendorTimeoutError, "UNAVAILABLE"), (VendorRateLimitError, "QUOTA"),
])
def test_retryable_failure_keeps_celery_delay_and_run_stage(
    generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch, error_type: type[ProviderError], code: str,
) -> None:
    # Given retry budget and deterministic maximum jitter, without a broker or sleeping.
    case = generation_case
    error = error_type("token=synthetic-private-value")
    case.provider.generate.side_effect = error
    case.provider.transcribe.side_effect = error
    monkeypatch.setattr("celery.utils.time.random.randrange", lambda stop: stop - 1)
    retry = Mock(wraps=case.task.retry)
    monkeypatch.setattr(case.task, "retry", retry)
    case.task.push_request(id="provider-retry", args=case.args, kwargs={}, retries=1)
    try:
        # When Celery autoretry receives the real runner exception (direct-call retry raises it).
        with pytest.raises(ProviderError) as raised:
            case.task.run(*case.args)
    finally:
        case.task.pop_request()
    # Then the exact typed instance reaches retry, retaining existing exponential delay.
    assert raised.value is error
    if isinstance(error, VendorRateLimitError):
        assert error.retry_after == 73
    if isinstance(error, VendorTimeoutError):
        assert error.timeout_seconds == 17
    retry.assert_called_once()
    assert retry.call_args.kwargs == {"exc": error, "countdown": 2 * int(case.task.retry_backoff)}
    assert case.task.autoretry_for == (ProviderTimeoutError, RateLimitError)
    assert case.task.retry_jitter is True
    assert case.provider.generate.await_count + case.provider.transcribe.await_count == 1
    saved = run_in_worker_loop(case.runner.runs.storage.get_run(case.runner.run_id))
    assert (saved["current_stage"], saved["status"]) == (case.stage, "running")
    tracked = run_in_worker_loop(case.runner.tracking.list_run_tasks(case.runner.run_id))[0]
    assert tracked.error_code == code


def test_soft_timeout_stays_distinct(generation_case: GenerationCase, monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a Celery soft limit during an actual provider call.
    case = generation_case
    error = SoftTimeLimitExceeded()
    case.provider.generate.side_effect = error
    case.provider.transcribe.side_effect = error
    retry = Mock(wraps=case.task.retry)
    monkeypatch.setattr(case.task, "retry", retry)
    # When the real task receives the signal exception.
    with pytest.raises(SoftTimeLimitExceeded) as raised:
        case.task.run(*case.args)
    # Then it is not translated or treated as a provider retry/fallback.
    assert raised.value is error
    retry.assert_not_called()
    assert case.provider.generate.await_count + case.provider.transcribe.await_count == 1
