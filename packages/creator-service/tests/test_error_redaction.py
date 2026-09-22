import json

import pytest
from creator_domain.exceptions import VersionConflictError
from creator_service.actionable_errors import map_service_error, redact_error_message
from creator_service.error_redaction import JsonValue, sanitize_error_json


@pytest.mark.parametrize("resource_id", [42, "timeline-42"])
def test_safe_version_fields_are_preserved(resource_id: int | str) -> None:
    # Given
    error = VersionConflictError(resource_id, 2, 3)
    # When
    encoded = json.dumps(map_service_error(error).version_conflict)
    # Then
    assert json.loads(encoded) == {
        "resource_id": resource_id, "expected_version": 2, "actual_version": 3,
    }


def test_safe_json_details_survive_serialization() -> None:
    # Given
    safe: JsonValue = {"run_id": 42, "task_name": "generate_script", "details": [None, True, 1.5, "Invalid input"]}
    # When
    encoded = json.dumps(sanitize_error_json(safe), allow_nan=False)
    # Then
    assert json.loads(encoded) == safe


def test_branching_input_is_globally_bounded() -> None:
    # Given: shared subtrees would expand exponentially without a total node budget.
    tree: JsonValue = "safe"
    for _ in range(10):
        tree = [tree] * 50
    # When
    encoded = json.dumps(sanitize_error_json(tree))
    # Then
    assert len(encoded) < 10000


@pytest.mark.parametrize("text", ["x" * 9000, "x" * 1020 + " sk-syntheticPrivate123456"])
def test_redaction_bounds_output_without_splitting_secrets(text: str) -> None:
    # Given / When
    redacted = redact_error_message(text)
    # Then
    assert len(redacted) <= 1024
    assert "sk-" not in redacted


class HookedString(str):
    def __str__(self) -> str:
        raise AssertionError("Stringification must not run")


@pytest.mark.parametrize("data", [HookedString("synthetic"), {HookedString("synthetic"): "private"}])
def test_custom_primitive_hooks_are_never_called(data: object) -> None:
    # Given / When
    encoded = json.dumps(sanitize_error_json(data), allow_nan=False)
    # Then
    assert "synthetic" not in encoded
    assert "private" not in encoded
