from __future__ import annotations

from typing import Any

import httpx

from creator_provider.base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        # model_key is our internal catalog key (e.g. "qwen3-4b").
        # Ollama expects the actual model tag (e.g. "qwen3:4b").
        # Convert dashes to colons for Ollama compatibility.
        self.model_name = model_key.replace("-", ":", 1)

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        # Use the /api/chat endpoint with think=false to disable Qwen3's
        # extended thinking mode, which is far too slow on consumer GPUs.
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"num_predict": 2048},
        }
        if params:
            payload.update(params)

        url = f"{self.endpoint}/api/chat"
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
        return str(data.get("message", {}).get("content", ""))
