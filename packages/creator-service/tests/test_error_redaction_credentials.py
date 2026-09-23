"""Registered #701 credential families, using exclusively synthetic values."""

import json

import pytest

from creator_service.error_redaction import JsonValue, redact_error_message, sanitize_error_json


@pytest.mark.parametrize(
    "credential",
    [
        "gsk_syntheticPrivate_123456789",
        "AIzaSyntheticPrivate_123456789-abcd",
        "sk-proj-syntheticPrivate_123456789_tail",
        "postgresql://synthetic:private-password@db.invalid:5432/studio",
        "redis://:private-password@redis.invalid:6379/0",
        "Bearer synthetic.private_token-123+/=",
        "bEaReR\tsynthetic.private_token-123",
    ],
)
def test_registered_credentials_are_fully_redacted(credential: str) -> None:
    # Given
    diagnostic = f"Provider unavailable: {credential}; retry later"
    # When
    redacted = redact_error_message(diagnostic)
    # Then: suffixes cannot survive partial prefix matches.
    assert redacted == "Provider unavailable: <redacted>; retry later"


@pytest.mark.parametrize("identifier", ["timeline-42", "run_701", "550e8400-e29b-41d4-a716-446655440000"])
def test_ordinary_identifiers_keep_their_meaning(identifier: str) -> None:
    # Given / When
    redacted = redact_error_message(f"Resource {identifier} not found")
    # Then
    assert redacted == f"Resource {identifier} not found"


def test_nested_credentials_are_redacted_without_mutating_input() -> None:
    # Given
    value = {"detail": [{"message": "Bearer syntheticPrivateValue", "run_id": 701}]}
    # When
    encoded = json.dumps(sanitize_error_json(value))
    # Then
    assert json.loads(encoded) == {"detail": [{"message": "<redacted>", "run_id": 701}]}
    assert value["detail"][0]["message"] == "Bearer syntheticPrivateValue"


def test_cycles_terminate_at_the_existing_depth_boundary() -> None:
    # Given
    cycle: list[JsonValue] = []
    cycle.append(cycle)
    # When
    encoded = json.dumps(sanitize_error_json(cycle))
    # Then
    assert len(encoded) < 100
    assert "<nested>" in encoded
