import asyncio
import time
from importlib import import_module

import pytest
from fastapi import HTTPException

admin = import_module("shorts_api.routes.admin")


class TestDestructiveOpRateLimiter:
    """Test the in-memory rate limiter for destructive operations."""

    def test_rate_limiter_allows_operations_under_limit(self) -> None:
        """Operations should be allowed when under the limit."""
        limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=3)
        admin_key = "test-admin-key"

        assert limiter.is_allowed(admin_key) is True
        assert limiter.is_allowed(admin_key) is True
        assert limiter.is_allowed(admin_key) is True

    def test_rate_limiter_rejects_operations_over_limit(self) -> None:
        """Operations should be rejected when over the limit."""
        limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=2)
        admin_key = "test-admin-key"

        assert limiter.is_allowed(admin_key) is True
        assert limiter.is_allowed(admin_key) is True
        assert limiter.is_allowed(admin_key) is False

    def test_rate_limiter_resets_after_one_minute(self) -> None:
        """Old operations should be cleaned up after one minute."""
        limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=1)
        admin_key = "test-admin-key"

        # First operation is allowed
        assert limiter.is_allowed(admin_key) is True

        # Second operation is rejected (within 1 minute)
        assert limiter.is_allowed(admin_key) is False

        # Manually set timestamp to be over 60 seconds old
        limiter.operations[admin_key][0] = time.time() - 61

        # Third operation should now be allowed
        assert limiter.is_allowed(admin_key) is True

    def test_rate_limiter_tracks_per_admin_key(self) -> None:
        """Different admin keys should have separate rate limits."""
        limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=1)

        assert limiter.is_allowed("key1") is True
        assert limiter.is_allowed("key2") is True

        # Both can have their next operation rejected independently
        assert limiter.is_allowed("key1") is False
        assert limiter.is_allowed("key2") is False

    def test_rate_limiter_get_remaining_ops(self) -> None:
        """get_remaining_ops should return correct count."""
        limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=3)
        admin_key = "test-key"

        assert limiter.get_remaining_ops(admin_key) == 3
        limiter.is_allowed(admin_key)
        assert limiter.get_remaining_ops(admin_key) == 2
        limiter.is_allowed(admin_key)
        assert limiter.get_remaining_ops(admin_key) == 1


class TestConfirmationHeaderRequired:
    """Test that destructive operations require confirmation header."""

    def test_require_confirmation_rejects_missing_header(self) -> None:
        """Should raise 400 when X-Confirm-Action header is missing."""
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                admin.require_confirmation_and_rate_limit(
                    x_confirm_action=None, x_admin_key="test-key"
                )
            )

        assert exc_info.value.status_code == 400
        assert "X-Confirm-Action: yes" in exc_info.value.detail

    def test_require_confirmation_rejects_wrong_value(self) -> None:
        """Should raise 400 when X-Confirm-Action value is not 'yes'."""
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                admin.require_confirmation_and_rate_limit(
                    x_confirm_action="no", x_admin_key="test-key"
                )
            )

        assert exc_info.value.status_code == 400

    def test_require_confirmation_accepts_case_insensitive_yes(self) -> None:
        """Should accept 'yes' in any case."""
        # Should not raise
        asyncio.run(
            admin.require_confirmation_and_rate_limit(
                x_confirm_action="YES", x_admin_key="test-key"
            )
        )
        asyncio.run(
            admin.require_confirmation_and_rate_limit(
                x_confirm_action="Yes", x_admin_key="test-key"
            )
        )
        asyncio.run(
            admin.require_confirmation_and_rate_limit(
                x_confirm_action="yes", x_admin_key="test-key"
            )
        )

    def test_require_confirmation_enforces_rate_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should enforce rate limit after confirmation passes."""
        # Create a new rate limiter with low limit for testing
        test_limiter = admin.DestructiveOpRateLimiter(max_ops_per_minute=1)
        monkeypatch.setattr(admin, "_rate_limiter", test_limiter)

        admin_key = "rate-limit-test-key"

        # First call succeeds
        asyncio.run(
            admin.require_confirmation_and_rate_limit(x_confirm_action="yes", x_admin_key=admin_key)
        )

        # Second call fails due to rate limit
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                admin.require_confirmation_and_rate_limit(
                    x_confirm_action="yes", x_admin_key=admin_key
                )
            )

        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.detail

class TestAdminEndpointSafeguards:
    """Integration tests for destructive admin endpoints with safeguards."""

    @pytest.fixture
    def mock_admin_service(self) -> None:
        """Mock the admin service."""
        # This would require setting up the FastAPI test client
        # For now, we're testing the middleware logic directly
        pass

    def test_unstick_run_requires_confirmation_header(self) -> None:
        """POST /runs/{run_id}/unstick requires X-Confirm-Action header."""
        # The middleware test above covers this
        # Here we verify the endpoint has the dependency
        import inspect

        # Check that the unstick endpoint has the rate limit dependency
        unstick_func = admin.admin_unstick_run
        sig = inspect.signature(unstick_func)
        assert "_" in sig.parameters
        assert "require_confirmation_and_rate_limit" in str(sig.parameters["_"].default)

    def test_cache_clear_requires_confirmation_header(self) -> None:
        """POST /cache/clear requires X-Confirm-Action header."""
        import inspect

        # Check that the cache_clear endpoint has the rate limit dependency
        clear_func = admin.admin_clear_cache
        sig = inspect.signature(clear_func)
        assert "_" in sig.parameters
        assert "require_confirmation_and_rate_limit" in str(sig.parameters["_"].default)

    def test_non_destructive_endpoints_dont_require_confirmation(self) -> None:
        """GET endpoints should not require confirmation header."""
        import inspect

        # Health endpoint should not have confirmation dependency
        health_func = admin.admin_health
        sig = inspect.signature(health_func)
        params = list(sig.parameters.keys())
        # Should only have standard params, not the confirmation one
        assert "_" not in params or "require_confirmation" not in str(sig)

        # Stuck runs endpoint should not have confirmation dependency
        stuck_func = admin.admin_stuck_runs
        sig = inspect.signature(stuck_func)
        params = list(sig.parameters.keys())
        assert "_" not in params or "require_confirmation" not in str(sig)
