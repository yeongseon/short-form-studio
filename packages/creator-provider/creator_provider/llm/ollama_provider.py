from __future__ import annotations

from typing import Any, cast

import httpx

from creator_provider.base import LLMProvider
from creator_provider.exceptions import ProviderError, map_httpx_error
from creator_provider.validation import MAX_LLM_PROMPT_CHARS, validate_prompt_length
from creator_provider.versioned_assets import get_tool_definition


class OllamaProvider(LLMProvider):
    def __init__(self, endpoint: str, model_key: str):
        self.endpoint = endpoint.rstrip("/")
        # model_key is our internal catalog key (e.g. "qwen3-4b").
        # Ollama expects the actual model tag (e.g. "qwen3:4b").
        # Convert dashes to colons for Ollama compatibility.
        self.model_name = model_key.replace("-", ":", 1)

    async def generate(self, prompt: str, params: dict[str, Any] | None = None) -> str:
        validate_prompt_length(prompt, MAX_LLM_PROMPT_CHARS, "LLM")
        # Use the /api/chat endpoint with think=false to disable Qwen3's
        # extended thinking mode, which is far too slow on consumer GPUs.
        message_template = cast(
            dict[str, str], get_tool_definition("llm_chat_message")["message_template"]
        )
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {
                    "role": message_template["role"],
                    "content": message_template["content"].format(prompt=prompt),
                }
            ],
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
            raise map_httpx_error(exc, f"Ollama at {url}") from exc

        data = response.json()
        content = str(data.get("message", {}).get("content", ""))
        if not content:
            raise ProviderError("Ollama returned empty content")
        return content
