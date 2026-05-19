"""Production environment safety checks.

When ``ENVIRONMENT`` is set to ``production`` or ``staging``, critical
configuration is validated at startup.  Missing or unsafe values cause an
immediate ``RuntimeError`` so the service never starts in a broken state.

In development (the default), all checks are skipped.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_UNSAFE_DB_PASSWORDS = frozenset(
    {
        "change-me-before-use",
        "password",
        "postgres",
        "secret",
        "changeme",
        "",
    }
)

_CHECKED_ENVIRONMENTS = frozenset({"production", "staging"})


class ProductionConfigError(RuntimeError):
    """Raised when production configuration is invalid."""


def _check_database_url(database_url: str, errors: list[str]) -> None:
    """Validate DATABASE_URL is set and does not use unsafe credentials."""
    if not database_url.strip():
        errors.append("DATABASE_URL is required in production.")
        return
    try:
        parsed = urlparse(database_url)
        db_password = parsed.password or ""
        if db_password.lower().strip() in _UNSAFE_DB_PASSWORDS:
            errors.append(
                "DATABASE_URL contains a default or empty password. "
                "Set a strong password in the connection string."
            )
    except Exception:
        errors.append("DATABASE_URL could not be parsed. Check the format.")


def validate_production_config(*, service_kind: str = "api") -> None:
    """Run safety checks when ``ENVIRONMENT`` is ``production`` or ``staging``."""
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment not in _CHECKED_ENVIRONMENTS:
        if environment != "development":
            logger.info("ENVIRONMENT=%s — skipping production checks", environment)
        return

    logger.info("ENVIRONMENT=%s — running startup safety checks", environment)
    errors: list[str] = []

    requires_http_config = service_kind.lower() == "api"

    # 2. DATABASE_URL must be set with safe credentials
    database_url = os.getenv("DATABASE_URL", "")
    _check_database_url(database_url, errors)

    if requires_http_config:
        cors_origins = os.getenv("CORS_ORIGINS", "")
        if not cors_origins.strip():
            errors.append(
                "CORS_ORIGINS is required in production. "
                "Set to the actual frontend origin(s), e.g. 'https://studio.example.com'."
            )
        elif "*" in cors_origins:
            errors.append(
                "CORS_ORIGINS must not contain wildcards ('*') in production. "
                "List specific allowed origins."
            )

    # 4. REDIS_URL must be set
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url.strip():
        errors.append("REDIS_URL is required in production.")

    # 5. ADMIN_API_KEY must be set with minimum length in production
    if environment == "production" and "ADMIN_API_KEY" in os.environ:
        admin_api_key = os.getenv("ADMIN_API_KEY", "")
        if len(admin_api_key) < 16:
            errors.append("ADMIN_API_KEY must be set to at least 16 characters in production.")

    # 6. Warn about local artifact storage (non-fatal but logged)
    artifact_root = os.getenv("ARTIFACT_ROOT", "./data/artifacts")
    if artifact_root.startswith("./") or artifact_root == "data/artifacts":
        logger.warning(
            "ARTIFACT_ROOT=%s looks like a relative/local path. "
            "Consider using an absolute path or object storage in production.",
            artifact_root,
        )

    if errors:
        msg = "Production configuration errors:\n" + "\n".join(f"  - {e}" for e in errors)
        raise ProductionConfigError(msg)

    logger.info("Production safety checks passed")
