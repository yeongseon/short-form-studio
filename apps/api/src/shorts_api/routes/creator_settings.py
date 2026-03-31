from __future__ import annotations

import os
from pathlib import Path

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

_ENV_FILE = Path(os.getenv("ENV_FILE_PATH", "/data/GitHub/short-form-pipeline/.env"))


class ApiKeyUpdate(BaseModel):
    provider: str
    api_key: str


class ApiKeyStatus(BaseModel):
    provider: str
    label: str
    configured: bool
    masked: str


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••" if key else ""
    return "••••" + key[-4:]


def _read_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _ENV_FILE.exists():
        return result
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _write_env_file(updates: dict[str, str]) -> None:
    lines: list[str] = []
    updated_keys: set[str] = set()

    if _ENV_FILE.exists():
        for line in _ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                k = k.strip()
                if k in updates:
                    lines.append(f"{k}={updates[k]}")
                    updated_keys.add(k)
                    continue
            lines.append(line)

    for k, v in updates.items():
        if k not in updated_keys:
            lines.append(f"{k}={v}")

    _ENV_FILE.write_text("\n".join(lines) + "\n")


@router.get("/settings/api-keys")
async def list_api_keys() -> list[ApiKeyStatus]:
    env_data = _read_env_file()
    result: list[ApiKeyStatus] = []
    for provider, env_var in _PROVIDER_ENV_MAP.items():
        value = env_data.get(env_var, "") or os.getenv(env_var, "")
        value = value.strip()
        result.append(
            ApiKeyStatus(
                provider=provider,
                label=_PROVIDER_LABELS.get(provider, provider.title()),
                configured=bool(value),
                masked=_mask_key(value),
            )
        )
    return result


@router.post("/settings/api-keys")
async def update_api_key(body: ApiKeyUpdate) -> ApiKeyStatus:
    provider = body.provider.lower()
    env_var = _PROVIDER_ENV_MAP.get(provider)
    if env_var is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    _write_env_file({env_var: body.api_key})

    os.environ[env_var] = body.api_key

    return ApiKeyStatus(
        provider=provider,
        label=_PROVIDER_LABELS.get(provider, provider.title()),
        configured=bool(body.api_key.strip()),
        masked=_mask_key(body.api_key),
    )
