# pyright: reportPrivateUsage=false

"""P0-3: the demo Short must be actually sample-backed (renderable), not a bare run.

Locks that seed_demo_short materializes a NEW workspace-owned project with real
persisted placeholder asset bytes, a saved timeline whose segments reference the
DB-assigned asset ids (never the sample's fixed ids), and a run created LAST
against that real project — so the created run can actually preview/render.
"""

import pytest
from creator_domain.models import MediaSegment, Timeline
from creator_service.demo_seed import DemoShortSeedResult, seed_demo_short


class _StubProject:
    def __init__(self, project_id: int, workspace_id: int) -> None:
        self.id = project_id
        self.workspace_id = workspace_id


class _StubProjectService:
    def __init__(self) -> None:
        self._next = 100
        self.created: list[dict] = []

    async def create_project(self, *, title, source_type, idea_brief=None, workspace_id=None, **_):
        self._next += 1
        self.created.append(
            {"id": self._next, "title": title, "workspace_id": workspace_id}
        )
        return _StubProject(self._next, workspace_id)


class _StubUploadResult:
    def __init__(self, key: str, data: bytes) -> None:
        self.key = key
        self.size_bytes = len(data)
        self.checksum = "abc"
        self.storage_provider = "local"


class _StubStorage:
    def __init__(self) -> None:
        self.uploaded: dict[str, bytes] = {}

    def upload(self, key, data, content_type="application/octet-stream"):
        self.uploaded[key] = data
        return _StubUploadResult(key, data)


class _StubAssetStorage:
    def __init__(self) -> None:
        self._next = 500
        self.rows: dict[int, dict] = {}

    async def save_asset(self, row: dict) -> dict:
        self._next += 1
        saved = {**row, "id": self._next}
        self.rows[self._next] = saved
        return saved

    async def get_asset(self, asset_id: int, workspace_id: int):
        row = self.rows.get(asset_id)
        if row is None or row.get("workspace_id") != workspace_id:
            return None
        return row


class _StubMediaAssetService:
    def __init__(self, storage: _StubStorage, asset_storage: _StubAssetStorage) -> None:
        self._storage = storage
        self._asset_storage = asset_storage

    def _backend(self):
        return self._storage

    async def get_asset_owner(self, asset_id: int, workspace_id: int):
        row = await self._asset_storage.get_asset(asset_id, workspace_id)
        return None if row is None else row.get("project_id")


class _StubTimelineService:
    def __init__(self, owner) -> None:
        self.saved: dict[int, Timeline] = {}
        self._owner = owner

    async def save_timeline(self, *, project_id, workspace_id, timeline, expected_revision):
        # Enforce the real asset-ownership contract: every segment asset must be
        # owned by this project+workspace (proves the remap persisted correctly).
        for seg in timeline.segments:
            owner = await self._owner.get_asset_owner(seg.asset_id, workspace_id)
            if owner != project_id:
                from creator_domain.exceptions import ValidationError

                raise ValidationError("Timeline references unavailable asset(s)")
        if timeline.project_id != project_id:
            from creator_domain.exceptions import ValidationError

            raise ValidationError("project_id mismatch")
        self.saved[project_id] = timeline
        return timeline

    async def load_timeline(self, *, project_id, workspace_id):
        return self.saved.get(project_id)


class _StubRun:
    def __init__(self, project_id, workspace_id) -> None:
        self.project_id = project_id
        self.workspace_id = workspace_id
        self.current_stage = "IDEA_READY"
        self.status = "pending"


class _StubRunService:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []

    async def create_run(self, **kwargs):
        self.create_calls.append(kwargs)
        return _StubRun(kwargs["project_id"], kwargs["workspace_id"])


def _services():
    storage = _StubStorage()
    asset_storage = _StubAssetStorage()
    media = _StubMediaAssetService(storage, asset_storage)
    return {
        "project_service": _StubProjectService(),
        "media_asset_service": media,
        "timeline_service": _StubTimelineService(media),
        "run_service": _StubRunService(),
        "_storage": storage,
        "_asset_storage": asset_storage,
    }


@pytest.mark.asyncio
async def test_seed_creates_new_workspace_owned_project() -> None:
    svc = _services()
    result = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    assert isinstance(result, DemoShortSeedResult)
    assert svc["project_service"].created[0]["workspace_id"] == 7
    assert result.project_id == svc["project_service"].created[0]["id"]


@pytest.mark.asyncio
async def test_seed_persists_real_asset_bytes() -> None:
    svc = _services()
    await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    # At least one real byte object was uploaded to storage (renderable, not
    # metadata-only), and PNG bytes are non-empty and valid-signature.
    assert svc["_storage"].uploaded
    for data in svc["_storage"].uploaded.values():
        assert data.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_seed_timeline_references_db_asset_ids_not_sample_ids() -> None:
    svc = _services()
    result = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    timeline = svc["timeline_service"].saved[result.project_id]
    db_ids = set(svc["_asset_storage"].rows.keys())
    for seg in timeline.segments:
        assert seg.asset_id in db_ids
        assert seg.asset_id not in (10, 11)  # never the sample's fixed ids
    assert timeline.project_id == result.project_id


@pytest.mark.asyncio
async def test_seed_assets_are_owned_by_the_new_project_and_workspace() -> None:
    svc = _services()
    result = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    for row in svc["_asset_storage"].rows.values():
        assert row["workspace_id"] == 7
        assert row["project_id"] == result.project_id


@pytest.mark.asyncio
async def test_seed_creates_run_last_against_the_new_project() -> None:
    svc = _services()
    result = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    assert len(svc["run_service"].create_calls) == 1
    call = svc["run_service"].create_calls[0]
    assert call["project_id"] == result.project_id
    assert call["workspace_id"] == 7
    assert result.run.project_id == result.project_id


@pytest.mark.asyncio
async def test_seed_does_not_create_run_if_timeline_save_fails() -> None:
    svc = _services()

    async def _boom(*, project_id, workspace_id, timeline, expected_revision):
        from creator_domain.exceptions import ValidationError

        raise ValidationError("forced failure")

    svc["timeline_service"].save_timeline = _boom  # type: ignore[method-assign]
    from creator_domain.exceptions import ValidationError

    with pytest.raises(ValidationError):
        await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    # Run must NOT be created when content persistence failed.
    assert svc["run_service"].create_calls == []


@pytest.mark.asyncio
async def test_repeated_seeds_create_distinct_projects() -> None:
    svc = _services()
    a = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    b = await seed_demo_short(workspace_id=7, **_svc_kwargs(svc))
    assert a.project_id != b.project_id


def _svc_kwargs(svc: dict) -> dict:
    return {
        "project_service": svc["project_service"],
        "media_asset_service": svc["media_asset_service"],
        "timeline_service": svc["timeline_service"],
        "run_service": svc["run_service"],
    }
