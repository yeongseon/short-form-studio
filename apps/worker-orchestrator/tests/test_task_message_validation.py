from __future__ import annotations

import pytest

from tasks.task_runner import validate_task_message


def test_validate_task_message_accepts_valid_payload() -> None:
    payload = {
        "run_id": 123,
        "task_name": "generate_script",
        "args": ["topic"],
        "kwargs": {"language": "en"},
    }
    assert validate_task_message(payload)["run_id"] == 123


@pytest.mark.parametrize(
    "payload, error_match",
    [
        ({}, "missing required field: run_id"),
        ({"run_id": "123"}, "run_id must be int"),
        ({"run_id": 1, "task_name": 2}, "task_name must be str"),
        ({"run_id": 1, "args": "bad"}, "args must be list"),
        ({"run_id": 1, "kwargs": []}, "kwargs must be dict"),
    ],
)
def test_validate_task_message_rejects_malformed_payload(payload, error_match: str) -> None:
    with pytest.raises(ValueError, match=error_match):
        validate_task_message(payload)
