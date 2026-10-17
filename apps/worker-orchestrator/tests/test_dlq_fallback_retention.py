from pathlib import Path

from celery_dlq_fallback import append_fallback_entry, read_fallback_entries


def test_fallback_rotates_to_a_bounded_size_and_is_read_back(tmp_path: Path) -> None:
    # Given: a deliberately tiny durable fallback budget.
    path = tmp_path / "dlq.jsonl"

    # When
    for index in range(12):
        append_fallback_entry(path, {"task_id": f"task-{index}"}, max_bytes=96)

    # Then: current + one rotated segment are bounded and operationally retrievable.
    rotated = path.with_suffix(".jsonl.1")
    assert path.stat().st_size <= 96
    assert rotated.stat().st_size <= 96
    entries = read_fallback_entries(path, limit=20)
    assert entries
    assert entries[-1]["task_id"] == "task-11"
    assert len(entries) < 12


def test_fallback_reader_salvages_valid_entries_around_corruption(tmp_path: Path) -> None:
    # Given
    path = tmp_path / "dlq.jsonl"
    path.write_text('{"task_id":"valid-a"}\n{"broken"\n{"task_id":"valid-b"}\n')

    # When
    entries = read_fallback_entries(path, limit=10)

    # Then
    assert entries == [{"task_id": "valid-a"}, {"task_id": "valid-b"}]


def test_fallback_rejects_oversized_entry_without_partial_json(tmp_path: Path) -> None:
    # Given
    path = tmp_path / "dlq.jsonl"

    # When / Then
    try:
        append_fallback_entry(path, {"task_id": "x" * 100}, max_bytes=16)
    except ValueError:
        pass
    else:
        raise AssertionError("oversized fallback entry was accepted")
    assert not path.exists()
