from __future__ import annotations

import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from shorts_api.auth import CurrentUser, get_current_user

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
    configured: bool


@router.get("/settings/api-keys")
async def list_api_keys(user: CurrentUser = Depends(get_current_user)) -> list[ApiKeyStatus]:
    # No resource-scoped access helper: this endpoint reports process-level provider key presence only.
    result: list[ApiKeyStatus] = []
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        value = os.getenv(env_var, "").strip()
        result.append(
            ApiKeyStatus(
                provider=provider,
                label=_PROVIDER_LABELS.get(provider, provider.title()),
                configured=bool(value),
            )
        )
    return result
