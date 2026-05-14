from __future__ import annotations

from typing import Any, cast

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import LLMProvider
from creator_provider.exceptions import map_httpx_error
from creator_provider.versioned_assets import get_tool_definition


class OpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        api_key = resolve_api_key("openai")
        if api_key is None:
            raise ValueError("API key for 'openai' not configured")
        self.api_key: str = api_key

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        max_tokens = (params or {}).get("max_tokens", 2048)
        timeout = (params or {}).get("timeout", 120.0)

        message_template = cast(
            dict[str, str], get_tool_definition("llm_chat_message")["message_template"]
        )
        payload = {
            "model": self.model_key,
            "messages": [
                {
                    "role": message_template["role"],
                    "content": message_template["content"].format(prompt=prompt),
                }
            ],
            "max_tokens": max_tokens,
        }

        url = f"{self.endpoint}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise map_httpx_error(exc, "OpenAI API") from exc

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI API returned no choices")
        return str(choices[0].get("message", {}).get("content", ""))
