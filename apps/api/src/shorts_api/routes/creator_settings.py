from __future__ import annotations

import os

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["settings"])

_PROVIDER_ENV_MAP: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "stability": "STABILITY_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}

_PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google (Gemini / Imagen)",
    "stability": "Stability AI",
    "elevenlabs": "ElevenLabs",
}


class ApiKeyStatus(BaseModel):
    provider: str
    label: str
    env_var: str
    configured: bool
    masked: str | None = None


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••" if key else ""
    return "••••" + key[-4:]




@router.get("/settings/api-keys")
async def list_api_keys() -> list[ApiKeyStatus]:
    result: list[ApiKeyStatus] = []
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        value = os.getenv(env_var, "").strip()
        result.append(
            ApiKeyStatus(
                provider=provider,
                label=_PROVIDER_LABELS.get(provider, provider.title()),
                env_var=env_var,
                configured=bool(value),
                masked=_mask_key(value) if value else None,
            )
        )
    return result


