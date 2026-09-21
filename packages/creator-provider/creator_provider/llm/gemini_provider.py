from __future__ import annotations

from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import LLMProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_LLM_PROMPT_CHARS, validate_prompt_length


class GeminiProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        self.api_key: str = resolve_api_key("google")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        validate_prompt_length(prompt, MAX_LLM_PROMPT_CHARS, "LLM")
        timeout = (params or {}).get("timeout", 120.0)
        max_tokens = (params or {}).get("max_tokens", 2048)

        url = f"{self.endpoint}/v1beta/models/{self.model_key}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "Gemini API") from exc

        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise ProviderError("Gemini API returned no candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(part.get("text", "") for part in parts)
        if not text:
            raise ProviderError("Gemini API returned empty content")
        return text
