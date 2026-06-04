from __future__ import annotations

from typing import Any, cast

import httpx

from creator_provider.api_keys import resolve_api_key
from creator_provider.base import LLMProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_LLM_PROMPT_CHARS, validate_prompt_length
from creator_provider.versioned_assets import get_tool_definition


class GroqLLMProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint: str = endpoint.rstrip("/")
        self.model_key: str = model_key
        self.api_key: str = resolve_api_key("groq")

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        import asyncio

        validate_prompt_length(prompt, MAX_LLM_PROMPT_CHARS, "LLM")
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

        url = f"{self.endpoint}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        max_retries = 5
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(max_retries):
                try:
                    response = await client.post(url, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    raise map_httpx_error(exc, "Groq API") from exc

                if response.status_code == 429:
                    wait_time = min(10 * (2 ** attempt), 60)
                    import logging
                    logging.getLogger(__name__).warning(
                        "Groq LLM rate limited, waiting %ds (attempt %d/%d)",
                        wait_time, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait_time)
                    continue

                try:
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise map_httpx_error(exc, "Groq API") from exc

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    raise ProviderError("Groq API returned no choices")
                content = str(choices[0].get("message", {}).get("content", ""))
                if not content:
                    raise ProviderError("Groq API returned empty content")
                return content

        raise ProviderError(f"Groq API rate limited after {max_retries} retries")
