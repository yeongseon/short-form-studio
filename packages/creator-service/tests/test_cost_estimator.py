from creator_service.cost_estimator import estimate_cost


def test_llm_cost_estimation() -> None:
    cost = estimate_cost(
        "openai",
        "gpt-4o-mini",
        input_tokens=2000,
        output_tokens=1000,
    )
    assert cost == 0.0009


def test_image_cost_estimation() -> None:
    cost = estimate_cost("openai", "dall-e-3", image_count=3)
    assert cost == 0.12


def test_tts_cost_estimation() -> None:
    cost = estimate_cost("openai", "tts-1", audio_seconds=100)
    assert cost == 0.0025


def test_unknown_model_returns_zero() -> None:
    cost = estimate_cost("unknown", "unknown")
    assert cost == 0.0
