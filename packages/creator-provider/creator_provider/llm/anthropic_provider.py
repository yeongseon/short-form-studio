from __future__ import annotations

from typing import Any

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import LLMProvider
from creator_provider.versioned_assets import get_tool_definition


class AnthropicProvider(LLMProvider):
    _API_VERSION = "2023-06-01"

    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        api_key = resolve_api_key("anthropic")
        if api_key is None:
            raise ValueError("API key for 'anthropic' not configured")
        self.api_key: str = api_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        max_tokens = (params or {}).get("max_tokens", 2048)
        timeout = (params or {}).get("timeout", 120.0)
        message_template = get_tool_definition("llm_chat_message")["message_template"]

        payload = {
            "model": self.model_key,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": message_template["role"],
                    "content": message_template["content"].format(prompt=prompt),
                }
            ],
        }

        url = f"{self.endpoint}/v1/messages"
        headers: dict[str, str] = {
            "x-api-key": self.api_key,
            "anthropic-version": self._API_VERSION,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

        data = response.json()
        content_blocks = data.get("content", [])
        if not content_blocks:
            raise RuntimeError("Anthropic API returned no content blocks")
        return "".join(
            block.get("text", "") for block in content_blocks if block.get("type") == "text"
        )
