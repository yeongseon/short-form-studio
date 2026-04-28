"""Production environment safety checks.

When ``ENVIRONMENT`` is set to ``production``, critical configuration is
validated at startup.  Missing or unsafe values cause an immediate
``RuntimeError`` so the service never starts in a broken state.

In development (the default), all checks are skipped.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_UNSAFE_PASSWORDS = frozenset(
    {
        "change-me-before-use",
        "password",
        "postgres",
        "secret",
        "changeme",
        "",
    }
)


class ProductionConfigError(RuntimeError):
    """Raised when production configuration is invalid."""


def validate_production_config() -> None:
    """Run safety checks when ``ENVIRONMENT=production``.

    Does nothing when ``ENVIRONMENT`` is unset or any value other than
    ``production``.

    Raises:
        ProductionConfigError: If any required configuration is missing
            or unsafe for production use.
    """
    environment = os.getenv("ENVIRONMENT", "development").lower()
    if environment != "production":
        if environment != "development":
            logger.info("ENVIRONMENT=%s — skipping production checks", environment)
        return

    logger.info("ENVIRONMENT=production — running startup safety checks")
    errors: list[str] = []

    # 1. API_KEY must be set
    api_key = os.getenv("API_KEY", "")
    if not api_key.strip():
        errors.append(
            "API_KEY is required in production. Set a strong, random key to protect the API."
        )

    # 2. POSTGRES_PASSWORD must not be a default value
    pg_password = os.getenv("POSTGRES_PASSWORD", "")
    if pg_password.lower().strip() in _UNSAFE_PASSWORDS:
        errors.append(
            "POSTGRES_PASSWORD is empty or uses a default value. "
            "Set a strong password for the database."
        )

    # 3. DATABASE_URL must be set
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.strip():
        errors.append("DATABASE_URL is required in production.")

    # 4. CORS_ORIGINS must be set and not contain wildcards
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

    # 5. REDIS_URL must be set
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url.strip():
        errors.append("REDIS_URL is required in production.")

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
