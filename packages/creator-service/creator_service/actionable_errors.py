"""SF-78: actionable error mapping, redaction, and async failure summaries.

map_service_error derives a stable, type-based category (never status-based) with
correct retryability and STATIC recovery copy — raw exception detail is never
interpolated into user-facing steps, so paths/secrets cannot leak that way.
map_provider_error wraps a creator_provider ProviderError into the right
creator_domain ServiceError with a safe static detail. redact_error_message strips
filesystem paths, URLs, and secret-shaped tokens. build_run_failure_summary is the
async (worker) surface: a safe, categorized, redacted failure summary for a run
that transitioned to FAILED.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from creator_domain.exceptions import (
    ConflictError,
    DataIntegrityError,
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


class ErrorCategory(enum.Enum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    CONFLICT = "CONFLICT"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    QUOTA = "QUOTA"
    UNAVAILABLE = "UNAVAILABLE"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class ActionableError:
    code: str
    category: ErrorCategory
    retryable: bool
    recovery_steps: tuple[str, ...]
    version_conflict: dict[str, int | str] | None = None


_RECOVERY: dict[ErrorCategory, tuple[str, ...]] = {
    ErrorCategory.NOT_FOUND: (
        "Verify the id is correct",
        "Confirm you have access to this workspace",
    ),
    ErrorCategory.VALIDATION: (
        "Fix the highlighted input",
        "Check the required fields and try again",
    ),
    ErrorCategory.CONFLICT: (
        "Reload the current state",
        "Reapply your change, then try again",
    ),
    ErrorCategory.VERSION_CONFLICT: (
        "Refresh to load the latest revision",
        "Reapply your change on top of it",
        "Save again",
    ),
    ErrorCategory.QUOTA: (
        "Wait a moment and retry",
        "Check your provider quota or billing",
    ),
    ErrorCategory.UNAVAILABLE: (
        "Retry in a moment",
        "If it persists, check provider status",
    ),
    ErrorCategory.DATA_INTEGRITY: (
        "Retry the operation",
        "If it persists, contact support",
    ),
    ErrorCategory.INTERNAL: (
        "Retry the operation",
        "If it persists, contact support",
    ),
}

_RETRYABLE: frozenset[ErrorCategory] = frozenset(
    {ErrorCategory.QUOTA, ErrorCategory.UNAVAILABLE}
)


def _category_for(exc: ServiceError) -> ErrorCategory:
    # Order matters: VersionConflictError is a ConflictError subclass.
    if isinstance(exc, VersionConflictError):
        return ErrorCategory.VERSION_CONFLICT
    if isinstance(exc, NotFoundError):
        return ErrorCategory.NOT_FOUND
    if isinstance(exc, ValidationError):
        return ErrorCategory.VALIDATION
    if isinstance(exc, QuotaExceededError):
        return ErrorCategory.QUOTA
    if isinstance(exc, ServiceUnavailableError):
        return ErrorCategory.UNAVAILABLE
    if isinstance(exc, DataIntegrityError):
        return ErrorCategory.DATA_INTEGRITY
    if isinstance(exc, ConflictError):
        return ErrorCategory.CONFLICT
    return ErrorCategory.INTERNAL


def map_service_error(exc: ServiceError) -> ActionableError:
    category = _category_for(exc)
    version_conflict: dict[str, int | str] | None = None
    if isinstance(exc, VersionConflictError):
        version_conflict = {
            "resource_id": exc.resource_id,
            "expected_version": exc.expected_version,
            "actual_version": exc.actual_version,
        }
    return ActionableError(
        code=category.value,
        category=category,
        retryable=category in _RETRYABLE,
        recovery_steps=_RECOVERY[category],
        version_conflict=version_conflict,
    )


def map_provider_error(exc: ProviderError) -> ServiceError:
    # Never carry the provider's raw message (may hold upstream URL/body/token);
    # each branch emits a safe, static, user-facing detail instead.
    if isinstance(exc, ProviderTimeoutError):
        return ServiceUnavailableError("The provider request timed out")
    if isinstance(exc, RateLimitError):
        return QuotaExceededError("The provider rate limit was exceeded")
    if isinstance(exc, ProviderValidationError):
        return ValidationError("The provider rejected the request; check the input")
    if isinstance(exc, ProviderAuthError):
        return ValidationError("The provider is not configured or its credential is invalid")
    return ServiceUnavailableError("The provider is temporarily unavailable")


_ABS_POSIX_PATH = re.compile(r"(?:/[\w.\-]+){2,}/?")
_WORKSPACE_PATH = re.compile(r"\bworkspaces/[\w./\-]+")
_WINDOWS_PATH = re.compile(r"[A-Za-z]:\\[\\\w.\- ]+")
_URL = re.compile(r"\bhttps?://[^\s'\"]+")
_TOKEN_PREFIX = re.compile(r"\b(?:(?:sk|ghp|xoxb)[-_]|AKIA)[A-Za-z0-9\-]{6,}")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{20,}\b")
_REDACTED = "<redacted>"


def redact_error_message(text: str) -> str:
    if not text:
        return text
    redacted = _URL.sub(_REDACTED, text)
    redacted = _TOKEN_PREFIX.sub(_REDACTED, redacted)
    redacted = _WINDOWS_PATH.sub(_REDACTED, redacted)
    redacted = _WORKSPACE_PATH.sub(_REDACTED, redacted)
    redacted = _ABS_POSIX_PATH.sub(_REDACTED, redacted)
    redacted = _LONG_HEX.sub(_REDACTED, redacted)
    return redacted


_PROVIDER_MESSAGE: dict[ErrorCategory, str] = {
    ErrorCategory.UNAVAILABLE: "The provider was temporarily unavailable",
    ErrorCategory.QUOTA: "The provider rate limit was exceeded",
    ErrorCategory.VALIDATION: "The request could not be processed as given",
    ErrorCategory.INTERNAL: "The operation failed unexpectedly",
}


def build_run_failure_summary(exc: Exception) -> dict[str, object]:
    """Build a safe, categorized failure summary for a run that hit FAILED.

    Provider errors are mapped to the actionable ServiceError taxonomy; any other
    exception becomes a non-retryable INTERNAL summary. The message is static per
    category (never the raw exception text), so no path/secret/upstream body leaks.
    """
    if isinstance(exc, ProviderError):
        service_exc = map_provider_error(exc)
        mapped = map_service_error(service_exc)
    elif isinstance(exc, ServiceError):
        mapped = map_service_error(exc)
    else:
        mapped = ActionableError(
            code=ErrorCategory.INTERNAL.value,
            category=ErrorCategory.INTERNAL,
            retryable=False,
            recovery_steps=_RECOVERY[ErrorCategory.INTERNAL],
        )
    message = _PROVIDER_MESSAGE.get(mapped.category, "The operation failed")
    return {
        "code": mapped.code,
        "category": mapped.category.value,
        "retryable": mapped.retryable,
        "recovery_steps": list(mapped.recovery_steps),
        "message": message,
    }


def failure_summary_from_code(code: str | None) -> dict[str, object] | None:
    """Reconstruct the full actionable summary from a stored failure code.

    The worker persists only the safe category code; the read surface rebuilds
    the category/retryability/recovery steps so clients get actionable guidance
    without the worker having to store (and risk leaking) anything more.
    """
    if code is None:
        return None
    try:
        category = ErrorCategory(code)
    except ValueError:
        return None
    return {
        "code": category.value,
        "category": category.value,
        "retryable": category in _RETRYABLE,
        "recovery_steps": list(_RECOVERY[category]),
        "message": _PROVIDER_MESSAGE.get(category, "The operation failed"),
    }
