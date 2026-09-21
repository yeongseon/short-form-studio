"""SF-78: actionable error mapping, redaction, and async failure summary.

Locks that every ServiceError maps to a type-derived category with correct
retryability and static recovery copy, that provider errors map to the right
ServiceError subclass, that redaction strips paths/URLs/tokens/secrets, and that
the async run-failure summary never carries raw secrets or internal paths.
"""

import pytest
from creator_domain.exceptions import (
    ConflictError,
    DataIntegrityError,
    NoHistoryError,
    NotFoundError,
    QuotaExceededError,
    ServiceError,
    ServiceUnavailableError,
    ValidationError,
    VersionConflictError,
)
from creator_provider.exceptions import (
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
    ProviderValidationError,
    RateLimitError,
)
from creator_service.actionable_errors import (
    ErrorCategory,
    build_run_failure_summary,
    failure_summary_from_code,
    map_provider_error,
    map_service_error,
    redact_error_message,
)


# --- map_service_error: category + retryable per type ---


@pytest.mark.parametrize(
    "exc,category,retryable",
    [
        (NotFoundError("x"), ErrorCategory.NOT_FOUND, False),
        (ValidationError("x"), ErrorCategory.VALIDATION, False),
        (ConflictError("x"), ErrorCategory.CONFLICT, False),
        (NoHistoryError("x"), ErrorCategory.CONFLICT, False),
        (
            VersionConflictError(resource_id=7, expected_version=3, actual_version=5),
            ErrorCategory.VERSION_CONFLICT,
            False,
        ),
        (QuotaExceededError("x"), ErrorCategory.QUOTA, True),
        (ServiceUnavailableError("x"), ErrorCategory.UNAVAILABLE, True),
        (DataIntegrityError("x"), ErrorCategory.DATA_INTEGRITY, False),
        (ServiceError("x"), ErrorCategory.INTERNAL, False),
    ],
)
def test_map_service_error_category_and_retryable(exc, category, retryable) -> None:
    mapped = map_service_error(exc)
    assert mapped.category == category
    assert mapped.retryable is retryable
    assert mapped.recovery_steps
    assert mapped.code


def test_category_is_type_derived_not_status_derived() -> None:
    # DataIntegrityError and ServiceError share status 500 but differ in category.
    assert map_service_error(DataIntegrityError("x")).category == ErrorCategory.DATA_INTEGRITY
    assert map_service_error(ServiceError("x")).category == ErrorCategory.INTERNAL


def test_version_conflict_exposes_only_safe_structured_fields() -> None:
    mapped = map_service_error(
        VersionConflictError(resource_id=42, expected_version=2, actual_version=9)
    )
    assert mapped.version_conflict is not None
    assert mapped.version_conflict == {
        "resource_id": 42,
        "expected_version": 2,
        "actual_version": 9,
    }
    assert any("refresh" in step.lower() for step in mapped.recovery_steps)


def test_generic_conflict_has_no_version_fields() -> None:
    assert map_service_error(ConflictError("x")).version_conflict is None


def test_recovery_steps_do_not_interpolate_detail() -> None:
    secret_detail = "failed at /home/user/.env with key sk-abcdef1234567890abcdef"
    mapped = map_service_error(ValidationError(secret_detail))
    joined = " ".join(mapped.recovery_steps)
    assert "sk-" not in joined
    assert "/home/" not in joined
    assert ".env" not in joined


# --- map_provider_error ---


@pytest.mark.parametrize(
    "exc,expected_type,http,retryable",
    [
        (ProviderTimeoutError("api.x.com: timed out"), ServiceUnavailableError, 503, True),
        (RateLimitError("api.x.com: 429"), QuotaExceededError, 429, True),
        (ProviderValidationError("api.x.com: bad"), ValidationError, 400, False),
        (ProviderAuthError("api.x.com: 401 unauthorized token=sk-secret"), ValidationError, 400, False),
        (ProviderError("api.x.com: boom"), ServiceUnavailableError, 503, True),
    ],
)
def test_map_provider_error(exc, expected_type, http, retryable) -> None:
    mapped = map_provider_error(exc)
    assert isinstance(mapped, expected_type)
    assert mapped.http_status_code == http
    assert map_service_error(mapped).retryable is retryable


def test_provider_auth_error_does_not_leak_upstream_body() -> None:
    exc = ProviderAuthError("https://api.openai.com/v1: 401 token=sk-abcdef1234567890abcdef")
    mapped = map_provider_error(exc)
    assert "sk-" not in mapped.detail
    assert "api.openai.com" not in mapped.detail
    assert "401" not in mapped.detail


# --- redact_error_message ---


@pytest.mark.parametrize(
    "raw,forbidden",
    [
        ("read /home/user/project/.env failed", "/home/user"),
        ("path C:\\Users\\bob\\secret.txt missing", "C:\\Users"),
        ("open workspaces/1/assets/secret.png error", "workspaces/1/assets"),
        ("fetch https://api.provider.com/v1/x failed", "https://api.provider.com"),
        ("token sk-abcdef1234567890abcdef rejected", "sk-abcdef1234567890abcdef"),
        ("gh token ghp_abcdef1234567890ABCDEFghijk rejected", "ghp_abcdef1234567890ABCDEFghijk"),
        ("aws key AKIAIOSFODNN7EXAMPLE bad", "AKIAIOSFODNN7EXAMPLE"),
        ("slack xoxb-1234-5678-abcdefghij bad", "xoxb-1234-5678-abcdefghij"),
        ("hash a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6 mismatch", "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"),
    ],
)
def test_redaction_strips_sensitive_fragments(raw, forbidden) -> None:
    redacted = redact_error_message(raw)
    assert forbidden not in redacted


@pytest.mark.parametrize(
    "safe",
    [
        "Run 42 not found",
        "Version conflict for 7: expected 3, actual 5",
        "Invalid input",
        "revision 12 is stale",
    ],
)
def test_redaction_does_not_over_redact_safe_messages(safe) -> None:
    assert redact_error_message(safe) == safe


# --- build_run_failure_summary (async) ---


def test_failure_summary_for_provider_timeout_is_retryable() -> None:
    summary = build_run_failure_summary(ProviderTimeoutError("api.x.com: timed out"))
    assert summary["category"] == ErrorCategory.UNAVAILABLE.value
    assert summary["retryable"] is True
    assert summary["recovery_steps"]


def test_failure_summary_for_provider_auth_is_non_retryable_and_safe() -> None:
    summary = build_run_failure_summary(
        ProviderAuthError("https://api.openai.com/v1: 401 token=sk-abcdef1234567890abcdef")
    )
    assert summary["retryable"] is False
    blob = str(summary)
    assert "sk-" not in blob
    assert "api.openai.com" not in blob


def test_failure_summary_for_unknown_exception_is_safe_and_non_retryable() -> None:
    summary = build_run_failure_summary(
        RuntimeError("crash at /home/user/app/render.py with /tmp/secret")
    )
    assert summary["retryable"] is False
    assert summary["category"] == ErrorCategory.INTERNAL.value
    blob = str(summary)
    assert "/home/user" not in blob
    assert "/tmp/secret" not in blob


def test_failure_summary_shape() -> None:
    summary = build_run_failure_summary(RateLimitError("api.x.com: 429"))
    assert set(summary.keys()) == {"code", "category", "retryable", "recovery_steps", "message"}
    assert isinstance(summary["recovery_steps"], list)


# --- failure_summary_from_code (read-side reconstruction) ---


def test_failure_summary_from_code_reconstructs_full_summary() -> None:
    summary = failure_summary_from_code("UNAVAILABLE")
    assert summary is not None
    assert summary["category"] == "UNAVAILABLE"
    assert summary["retryable"] is True
    assert summary["recovery_steps"]
    assert set(summary.keys()) == {"code", "category", "retryable", "recovery_steps", "message"}


def test_failure_summary_from_code_matches_build_for_provider_error() -> None:
    built = build_run_failure_summary(ProviderTimeoutError("api.x.com: timed out"))
    reconstructed = failure_summary_from_code(str(built["code"]))
    assert reconstructed == built


def test_failure_summary_from_code_none_for_unknown_or_missing() -> None:
    assert failure_summary_from_code(None) is None
    assert failure_summary_from_code("ValueError") is None
    assert failure_summary_from_code("not-a-category") is None
