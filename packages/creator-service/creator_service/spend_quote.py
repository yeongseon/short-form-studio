from decimal import Decimal, InvalidOperation
from typing import Final

MONEY_SCALE: Final = Decimal("0.000001")
MAX_AUDIO_DURATION_SECONDS: Final = Decimal("3600")


def _finite_non_negative(value: Decimal, name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be finite and non-negative") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return parsed


def image_reservation_quote(
    *, scene_count: int, internal_attempts: int, max_retries: int,
    cost_per_attempt: Decimal,
) -> Decimal:
    if scene_count <= 0 or internal_attempts <= 0 or max_retries < 0:
        raise ValueError("image quote dimensions must be positive")
    cost = _finite_non_negative(cost_per_attempt, "cost_per_attempt")
    deliveries = max_retries + 1
    return (cost * scene_count * internal_attempts * deliveries).quantize(MONEY_SCALE)


def audio_reservation_quote(
    *, duration_seconds: Decimal, max_retries: int, cost_per_second: Decimal,
) -> Decimal:
    duration = _finite_non_negative(duration_seconds, "duration_seconds")
    if duration <= 0 or duration > MAX_AUDIO_DURATION_SECONDS:
        raise ValueError("duration_seconds is outside the supported duration bound")
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    cost = _finite_non_negative(cost_per_second, "cost_per_second")
    return (duration * cost * (max_retries + 1)).quantize(MONEY_SCALE)
