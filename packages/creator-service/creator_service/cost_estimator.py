PRICING = {
    "openai/gpt-4o-mini": {"input_per_1k": 0.00015, "output_per_1k": 0.0006},
    "openai/gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01},
    "anthropic/claude-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "google/gemini-2.0-flash": {"input_per_1k": 0.0001, "output_per_1k": 0.0004},
    "openai/dall-e-3": {"per_image": 0.04},
    "stability/sd3-medium": {"per_image": 0.035},
    "google/imagen-3": {"per_image": 0.03},
    "elevenlabs/multilingual-v2": {"per_second": 0.0003},
    "openai/tts-1": {"per_second": 0.000025},
}


def estimate_cost(
    provider: str,
    model_key: str,
    *,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    image_count: int | None = None,
    audio_seconds: float | None = None,
) -> float:
    pricing = PRICING.get(f"{provider}/{model_key}")
    if pricing is None:
        return 0.0

    if "input_per_1k" in pricing or "output_per_1k" in pricing:
        input_cost = ((input_tokens or 0) / 1000.0) * float(pricing.get("input_per_1k", 0.0))
        output_cost = ((output_tokens or 0) / 1000.0) * float(pricing.get("output_per_1k", 0.0))
        return input_cost + output_cost

    if "per_image" in pricing:
        return float(image_count or 0) * float(pricing["per_image"])

    if "per_second" in pricing:
        return float(audio_seconds or 0.0) * float(pricing["per_second"])

    return 0.0
