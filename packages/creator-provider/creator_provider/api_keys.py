"""API key resolution for external providers.

Keys are read from environment variables with standard naming:
  OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY,
  STABILITY_API_KEY, ELEVENLABS_API_KEY

Usage:
  from creator_provider.api_keys import resolve_api_key
  key = resolve_api_key("openai")  # reads OPENAI_API_KEY
"""
from __future__ import annotations

import os

from creator_provider.exceptions import ProviderAuthError, ProviderValidationError

# Canonical mapping: provider_name -> env var name
_KEY_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "stability": "STABILITY_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
    "groq": "GROQ_API_KEY",
}


def resolve_api_key(provider_name: str, *, required: bool = True) -> str | None:
    """Resolve an API key for the given provider from environment variables.

    Args:
        provider_name: Provider name (e.g. "openai", "anthropic", "google", "stability", "elevenlabs")
        required: If True, raise ValueError when key is missing/empty. Default True.

    Returns:
        The API key string, or None if required=False and key is not set.

    Raises:
        ValueError: If provider_name is unknown or key is missing when required=True.
    """
    env_var = _KEY_MAP.get(provider_name.lower())
    if env_var is None:
        raise ProviderValidationError(
            f"Unknown provider '{provider_name}'. Known providers: {', '.join(sorted(_KEY_MAP.keys()))}"
        )

    value = os.getenv(env_var, "").strip()
    if not value:
        if required:
            raise ProviderAuthError(
                f"API key for '{provider_name}' not configured. Set the {env_var} environment variable."
            )
        return None
    return value


def list_configured_providers() -> list[str]:
    """Return a list of provider names that have API keys configured."""
    return [
        name
        for name, env_var in _KEY_MAP.items()
        if os.getenv(env_var, "").strip()
    ]
