from __future__ import annotations

from typing import Any

import httpx

from creator_provider.base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        self.model_key = model_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model_key,
            "prompt": prompt,
            "stream": False,
        }
        if params:
            payload.update(params)

        url = f"{self.endpoint}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Failed to connect to Ollama provider at {url}: {exc}") from exc

        data = response.json()
        return str(data["response"])
