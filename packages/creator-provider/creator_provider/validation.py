"""Shared input validation for provider adapters."""

MAX_LLM_PROMPT_CHARS = 32_000
MAX_IMAGE_PROMPT_CHARS = 2_000
MAX_TTS_TEXT_CHARS = 5_000


def validate_prompt_length(prompt: str, max_chars: int, provider_name: str = "provider") -> None:
    """Raise ValueError if prompt exceeds max_chars."""
    if len(prompt) > max_chars:
        raise ValueError(f"{provider_name} prompt too long: {len(prompt)} chars (max {max_chars})")
