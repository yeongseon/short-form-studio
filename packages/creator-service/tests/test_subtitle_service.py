import asyncio

import pytest
from creator_service.subtitle_service import (
    InMemorySubtitleStorage,
    SubtitleService,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def storage() -> InMemorySubtitleStorage:
    return InMemorySubtitleStorage()


@pytest.fixture
def service(storage: InMemorySubtitleStorage) -> SubtitleService:
    return SubtitleService(storage)


# -- create_artifact ---------------------------------------------------------------


def test_create_artifact(service: SubtitleService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle.srt",
        )
    )

    assert artifact.run_id == 1
    assert artifact.path == "/data/artifacts/1/subtitle.srt"
    assert artifact.format == "srt"
    assert artifact.created_at is not None


def test_create_artifact_with_metadata(service: SubtitleService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle.vtt",
            format="vtt",
            model_used="whisper-large",
            provider_type="openai",
        )
    )

    assert artifact.run_id == 1
    assert artifact.path == "/data/artifacts/1/subtitle.vtt"
    assert artifact.format == "vtt"
    assert artifact.created_at is not None


def test_create_artifact_default_format(service: SubtitleService) -> None:
    """Verify default format is 'srt'."""
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle.srt",
        )
    )

    assert artifact.format == "srt"


def test_create_artifact_has_id(service: SubtitleService) -> None:
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle.srt",
        )
    )

    assert artifact.id is not None
    assert artifact.id > 0


# -- get_latest ---------------------------------------------------------------


def test_get_latest_returns_most_recent(service: SubtitleService) -> None:
    """Create 2 artifacts, get_latest returns newest."""
    first = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle_v1.srt",
        )
    )
    second = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle_v2.srt",
        )
    )

    latest = run(service.get_latest(run_id=1))

    assert latest is not None
    assert latest.id == second.id
    assert latest.id != first.id
    assert latest.path == "/data/artifacts/1/subtitle_v2.srt"


def test_get_latest_empty(service: SubtitleService) -> None:
    """Returns None when no artifacts."""
    latest = run(service.get_latest(run_id=999))

    assert latest is None


# -- list_by_run ---------------------------------------------------------------


def test_list_by_run_newest_first(service: SubtitleService) -> None:
    """Multiple artifacts, sorted by created_at desc."""
    a1 = run(service.create_artifact(run_id=1, path="/subtitle_1.srt"))
    a2 = run(service.create_artifact(run_id=1, path="/subtitle_2.srt"))
    a3 = run(service.create_artifact(run_id=1, path="/subtitle_3.srt"))

    artifacts = run(service.list_by_run(run_id=1))

    assert len(artifacts) == 3
    assert artifacts[0].id == a3.id
    assert artifacts[1].id == a2.id
    assert artifacts[2].id == a1.id


def test_list_by_run_empty(service: SubtitleService) -> None:
    """Returns empty list."""
    artifacts = run(service.list_by_run(run_id=999))

    assert artifacts == []


def test_list_by_run_filters_by_run(service: SubtitleService) -> None:
    """Create for run_id=1 and run_id=2, verify isolation."""
    run(service.create_artifact(run_id=1, path="/run1_subtitle.srt"))
    run(service.create_artifact(run_id=1, path="/run1_subtitle_v2.srt"))
    run(service.create_artifact(run_id=2, path="/run2_subtitle.srt"))

    run1_artifacts = run(service.list_by_run(run_id=1))
    run2_artifacts = run(service.list_by_run(run_id=2))

    assert len(run1_artifacts) == 2
    assert len(run2_artifacts) == 1
    assert all(a.run_id == 1 for a in run1_artifacts)
    assert all(a.run_id == 2 for a in run2_artifacts)


# -- get_by_id ---------------------------------------------------------------


def test_get_by_id(service: SubtitleService) -> None:
    """Fetch by specific id."""
    created = run(
        service.create_artifact(
            run_id=1,
            path="/data/artifacts/1/subtitle.srt",
        )
    )

    fetched = run(service.get_by_id(created.id))

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.path == "/data/artifacts/1/subtitle.srt"


def test_get_by_id_not_found(service: SubtitleService) -> None:
    """Returns None for nonexistent id."""
    fetched = run(service.get_by_id(999))

    assert fetched is None


# -- Concurrent saves -----------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_saves_produce_unique_ids() -> None:
    """Two concurrent saves must produce distinct ids."""
    storage = InMemorySubtitleStorage()
    svc = SubtitleService(storage)

    results = await asyncio.gather(
        svc.create_artifact(run_id=1, path="/a.srt"),
        svc.create_artifact(run_id=1, path="/b.srt"),
    )

    ids = sorted(a.id for a in results)
    assert ids == [1, 2], f"Expected unique ids [1, 2], got {ids}"


@pytest.mark.asyncio
async def test_concurrent_saves_across_service_instances() -> None:
    """Two service instances sharing storage must still produce unique ids."""
    storage = InMemorySubtitleStorage()
    service_a = SubtitleService(storage)
    service_b = SubtitleService(storage)

    results = await asyncio.gather(
        service_a.create_artifact(run_id=1, path="/a.srt"),
        service_b.create_artifact(run_id=1, path="/b.srt"),
    )

    ids = sorted(a.id for a in results)
    assert ids == [1, 2], f"Expected unique ids [1, 2], got {ids}"


# -- Isolation -------------------------------------------------------------------


def test_different_runs_have_independent_artifacts(service: SubtitleService) -> None:
    run(service.create_artifact(run_id=1, path="/r1_subtitle.srt"))
    run(service.create_artifact(run_id=2, path="/r2_subtitle.srt"))

    r1_artifacts = run(service.list_by_run(run_id=1))
    r2_artifacts = run(service.list_by_run(run_id=2))

    assert len(r1_artifacts) == 1
    assert len(r2_artifacts) == 1
    assert r1_artifacts[0].run_id == 1
    assert r2_artifacts[0].run_id == 2


def test_format_variations(service: SubtitleService) -> None:
    """Test both supported formats."""
    srt_artifact = run(
        service.create_artifact(
            run_id=1,
            path="/subtitle.srt",
            format="srt",
        )
    )
    vtt_artifact = run(
        service.create_artifact(
            run_id=1,
            path="/subtitle.vtt",
            format="vtt",
        )
    )

    assert srt_artifact.format == "srt"
    assert vtt_artifact.format == "vtt"

    latest = run(service.get_latest(run_id=1))
    assert latest is not None
    assert latest.format == "vtt"  # Most recent


def test_metadata_preservation(service: SubtitleService) -> None:
    """Verify metadata fields are preserved."""
    artifact = run(
        service.create_artifact(
            run_id=1,
            path="/subtitle.srt",
            format="vtt",
            model_used="whisper-small",
            provider_type="openai",
        )
    )

    fetched = run(service.get_by_id(artifact.id))
    assert fetched is not None
    assert fetched.format == "vtt"


def test_create_artifact_incremental_ids(service: SubtitleService) -> None:
    """IDs should increment sequentially."""
    a1 = run(service.create_artifact(run_id=1, path="/sub1.srt"))
    a2 = run(service.create_artifact(run_id=1, path="/sub2.srt"))
    a3 = run(service.create_artifact(run_id=2, path="/sub3.srt"))

    assert a1.id == 1
    assert a2.id == 2
    assert a3.id == 3
