"""Tests for typed service-layer exception hierarchy."""

from __future__ import annotations

import pytest

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


class TestExceptionHierarchy:
    """All typed exceptions inherit from ServiceError."""

    def test_not_found_is_service_error(self) -> None:
        assert issubclass(NotFoundError, ServiceError)

    def test_validation_is_service_error(self) -> None:
        assert issubclass(ValidationError, ServiceError)

    def test_conflict_is_service_error(self) -> None:
        assert issubclass(ConflictError, ServiceError)

    def test_version_conflict_is_conflict(self) -> None:
        assert issubclass(VersionConflictError, ConflictError)

    def test_quota_exceeded_is_service_error(self) -> None:
        assert issubclass(QuotaExceededError, ServiceError)

    def test_service_unavailable_is_service_error(self) -> None:
        assert issubclass(ServiceUnavailableError, ServiceError)

    def test_data_integrity_is_service_error(self) -> None:
        assert issubclass(DataIntegrityError, ServiceError)


class TestHttpStatusCodes:
    """Each exception carries the correct HTTP status code."""

    @pytest.mark.parametrize(
        "exc_class,expected_code",
        [
            (NotFoundError, 404),
            (ValidationError, 400),
            (ConflictError, 409),
            (VersionConflictError, 409),
            (QuotaExceededError, 429),
            (ServiceUnavailableError, 503),
            (DataIntegrityError, 500),
            (ServiceError, 500),
        ],
    )
    def test_status_code(self, exc_class: type[ServiceError], expected_code: int) -> None:
        assert exc_class.http_status_code == expected_code


class TestExceptionDetail:
    """Exceptions carry a detail message accessible via .detail."""

    def test_default_detail(self) -> None:
        assert NotFoundError().detail == "Not found"

    def test_custom_detail(self) -> None:
        exc = NotFoundError("Run 42 not found")
        assert exc.detail == "Run 42 not found"
        assert str(exc) == "Run 42 not found"

    def test_version_conflict_detail(self) -> None:
        exc = VersionConflictError(resource_id=7, expected_version=3, actual_version=5)
        assert exc.resource_id == 7
        assert exc.expected_version == 3
        assert exc.actual_version == 5
        assert "7" in exc.detail
        assert "3" in exc.detail
        assert "5" in exc.detail


class TestExceptionCatchability:
    """Typed exceptions can be caught by their base classes."""

    def test_catch_not_found_as_service_error(self) -> None:
        with pytest.raises(ServiceError):
            raise NotFoundError("gone")

    def test_catch_version_conflict_as_conflict(self) -> None:
        with pytest.raises(ConflictError):
            raise VersionConflictError(1, 2, 3)

    def test_catch_version_conflict_as_service_error(self) -> None:
        with pytest.raises(ServiceError):
            raise VersionConflictError(1, 2, 3)
