from decimal import Decimal

import pytest

from creator_service.spend_quote import audio_reservation_quote, image_reservation_quote


def test_image_quote_covers_scene_attempts_and_delivery_retries() -> None:
    # Given two scenes, three internal attempts, and five Celery retries.
    # When the immutable quote is calculated, then every possible provider attempt is covered.
    assert image_reservation_quote(
        scene_count=2,
        internal_attempts=3,
        max_retries=5,
        cost_per_attempt=Decimal("0.04"),
    ) == Decimal("1.440000")


def test_audio_quote_uses_bounded_duration_and_delivery_retries() -> None:
    # Given one minute of audio and five retries, when quoted, then six deliveries are covered.
    assert audio_reservation_quote(
        duration_seconds=Decimal("60"),
        max_retries=5,
        cost_per_second=Decimal("0.0003"),
    ) == Decimal("0.108000")


@pytest.mark.parametrize("duration", [Decimal("0"), Decimal("3600.000001")])
def test_audio_quote_rejects_unbounded_duration(duration: Decimal) -> None:
    # Given duration outside the supported billing bound, then admission cannot produce a quote.
    with pytest.raises(ValueError, match="duration"):
        audio_reservation_quote(
            duration_seconds=duration,
            max_retries=5,
            cost_per_second=Decimal("0.0003"),
        )
