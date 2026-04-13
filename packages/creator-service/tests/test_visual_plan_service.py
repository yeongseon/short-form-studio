import asyncio

import pytest
from creator_domain.models.visual_plan import VisualScene
from creator_service.visual_plan_service import (
    DataIntegrityError,
    InMemoryVisualPlanStorage,
    VersionConflictError,
    VisualPlanService,
)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def storage() -> InMemoryVisualPlanStorage:
    return InMemoryVisualPlanStorage()


@pytest.fixture
def service(storage: InMemoryVisualPlanStorage) -> VisualPlanService:
    return VisualPlanService(storage)


def _make_scene(
    scene_id: str = "sc-1",
    section_id: str = "sec-1",
    scene_index: int = 0,
    section_type: str = "hook",
    original_text: str = "Hook text",
    prompt: str = "A dramatic opening shot",
) -> VisualScene:
    return VisualScene(
        scene_id=scene_id,
        section_id=section_id,
        scene_index=scene_index,
        section_type=section_type,
        original_text=original_text,
        prompt=prompt,
    )


# -- save_plan ---------------------------------------------------------------


def test_save_plan_creates_version_1(service: VisualPlanService) -> None:
    scenes = [_make_scene()]
    plan = run(service.save_plan(run_id=101, scenes=scenes))

    assert plan.run_id == 101
    assert plan.version == 1
    assert len(plan.scenes) == 1
    assert plan.scenes[0].scene_id == "sc-1"


def test_save_plan_increments_version(service: VisualPlanService) -> None:
    scenes_v1 = [_make_scene(prompt="V1 prompt")]
    scenes_v2 = [_make_scene(prompt="V2 prompt")]

    run(service.save_plan(run_id=102, scenes=scenes_v1))
    second = run(service.save_plan(run_id=102, scenes=scenes_v2))

    assert second.version == 2
    assert second.scenes[0].prompt == "V2 prompt"


def test_save_plan_preserves_all_scene_fields(service: VisualPlanService) -> None:
    scene = VisualScene(
        scene_id="sc-full",
        section_id="sec-full",
        scene_index=2,
        section_type="body",
        original_text="Body text",
        prompt="Detailed body shot",
        prompt_edited=True,
        prompt_source="user_edited",
        style_tags=["cinematic", "dark"],
        mood="tense",
        composition="close-up",
        generation_status="completed",
        latest_asset_id=42,
    )
    plan = run(service.save_plan(run_id=103, scenes=[scene]))

    saved_scene = plan.scenes[0]
    assert saved_scene.prompt_edited is True
    assert saved_scene.prompt_source == "user_edited"
    assert saved_scene.style_tags == ["cinematic", "dark"]
    assert saved_scene.mood == "tense"
    assert saved_scene.composition == "close-up"
    assert saved_scene.generation_status == "completed"
    assert saved_scene.latest_asset_id == 42


def test_save_plan_multi_scene(service: VisualPlanService) -> None:
    scenes = [
        _make_scene(scene_id="sc-1", scene_index=0, section_type="hook"),
        _make_scene(scene_id="sc-2", scene_index=1, section_type="body"),
        _make_scene(scene_id="sc-3", scene_index=2, section_type="cta"),
    ]
    plan = run(service.save_plan(run_id=104, scenes=scenes))

    assert len(plan.scenes) == 3
    assert [s.scene_id for s in plan.scenes] == ["sc-1", "sc-2", "sc-3"]
    assert [s.scene_index for s in plan.scenes] == [0, 1, 2]


# -- patch_scene --------------------------------------------------------------


def test_patch_scene_updates_prompt(service: VisualPlanService) -> None:
    scenes = [
        _make_scene(scene_id="sc-1", prompt="Original prompt"),
        _make_scene(scene_id="sc-2", scene_index=1, prompt="Keep this"),
    ]
    run(service.save_plan(run_id=201, scenes=scenes))

    plan = run(
        service.patch_scene(
            run_id=201,
            scene_id="sc-1",
            updates={"prompt": "Edited prompt", "prompt_edited": True},
        )
    )

    assert plan.version == 2
    patched = next(s for s in plan.scenes if s.scene_id == "sc-1")
    assert patched.prompt == "Edited prompt"
    assert patched.prompt_edited is True

    untouched = next(s for s in plan.scenes if s.scene_id == "sc-2")
    assert untouched.prompt == "Keep this"


def test_patch_scene_raises_when_no_active_plan(service: VisualPlanService) -> None:
    with pytest.raises(ValueError, match="No active visual plan"):
        run(service.patch_scene(run_id=999, scene_id="sc-1", updates={"prompt": "x"}))


def test_patch_scene_raises_when_scene_not_found(service: VisualPlanService) -> None:
    scenes = [_make_scene(scene_id="sc-1")]
    run(service.save_plan(run_id=203, scenes=scenes))

    with pytest.raises(ValueError, match="Scene 'sc-missing' not found"):
        run(
            service.patch_scene(
                run_id=203, scene_id="sc-missing", updates={"prompt": "x"}
            )
        )


# -- patch_scene: expected_version (optimistic concurrency) -------------------


def test_patch_scene_with_matching_expected_version(service: VisualPlanService) -> None:
    """Patch succeeds when expected_version matches active version."""
    run(service.save_plan(run_id=210, scenes=[_make_scene()]))

    plan = run(
        service.patch_scene(
            run_id=210,
            scene_id="sc-1",
            updates={"prompt": "Updated"},
            expected_version=1,
        )
    )
    assert plan.version == 2
    assert plan.scenes[0].prompt == "Updated"


def test_patch_scene_with_stale_expected_version(service: VisualPlanService) -> None:
    """Patch raises VersionConflictError when expected_version is stale."""
    run(service.save_plan(run_id=211, scenes=[_make_scene()]))
    # Advance to version 2
    run(service.save_plan(run_id=211, scenes=[_make_scene(prompt="V2")]))

    with pytest.raises(VersionConflictError) as exc_info:
        run(
            service.patch_scene(
                run_id=211,
                scene_id="sc-1",
                updates={"prompt": "Stale"},
                expected_version=1,
            )
        )

    assert exc_info.value.run_id == 211
    assert exc_info.value.expected_version == 1
    assert exc_info.value.actual_version == 2


def test_patch_scene_skips_version_check_when_none(service: VisualPlanService) -> None:
    """Patch succeeds without version check when expected_version is None."""
    run(service.save_plan(run_id=212, scenes=[_make_scene()]))
    run(service.save_plan(run_id=212, scenes=[_make_scene(prompt="V2")]))

    # expected_version=None (default) — no check, always succeeds
    plan = run(
        service.patch_scene(
            run_id=212,
            scene_id="sc-1",
            updates={"prompt": "No version check"},
        )
    )
    assert plan.version == 3
    assert plan.scenes[0].prompt == "No version check"


@pytest.mark.asyncio
async def test_patch_scene_expected_version_is_atomic() -> None:
    storage = InMemoryVisualPlanStorage()
    service_a = VisualPlanService(storage)
    service_b = VisualPlanService(storage)

    await service_a.save_plan(run_id=213, scenes=[_make_scene(prompt="Base")])

    async def patch(service: VisualPlanService, prompt: str) -> str:
        plan = await service.patch_scene(
            run_id=213,
            scene_id="sc-1",
            updates={"prompt": prompt},
            expected_version=1,
        )
        return plan.scenes[0].prompt

    results = await asyncio.gather(
        patch(service_a, "A"),
        patch(service_b, "B"),
        return_exceptions=True,
    )

    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], VersionConflictError)


# -- patch_scene: field allowlist ----------------------------------------------


def test_patch_scene_rejects_scene_id(service: VisualPlanService) -> None:
    """Immutable identity field scene_id cannot be patched."""
    run(service.save_plan(run_id=220, scenes=[_make_scene()]))

    with pytest.raises(ValueError, match="immutable/unknown fields"):
        run(
            service.patch_scene(
                run_id=220, scene_id="sc-1", updates={"scene_id": "sc-hacked"}
            )
        )


def test_patch_scene_rejects_generation_status(service: VisualPlanService) -> None:
    """System-managed field generation_status cannot be patched."""
    run(service.save_plan(run_id=221, scenes=[_make_scene()]))

    with pytest.raises(ValueError, match="immutable/unknown fields"):
        run(
            service.patch_scene(
                run_id=221,
                scene_id="sc-1",
                updates={"generation_status": "completed"},
            )
        )


def test_patch_scene_rejects_latest_asset_id(service: VisualPlanService) -> None:
    """System-managed field latest_asset_id cannot be patched."""
    run(service.save_plan(run_id=222, scenes=[_make_scene()]))

    with pytest.raises(ValueError, match="immutable/unknown fields"):
        run(
            service.patch_scene(
                run_id=222,
                scene_id="sc-1",
                updates={"latest_asset_id": 99},
            )
        )


def test_patch_scene_rejects_unknown_field(service: VisualPlanService) -> None:
    """Completely unknown fields are rejected."""
    run(service.save_plan(run_id=223, scenes=[_make_scene()]))

    with pytest.raises(ValueError, match="immutable/unknown fields"):
        run(
            service.patch_scene(
                run_id=223,
                scene_id="sc-1",
                updates={"hackerfield": "pwned"},
            )
        )


# -- get_active_plan -----------------------------------------------------------


def test_get_active_plan_returns_latest(service: VisualPlanService) -> None:
    run(service.save_plan(run_id=301, scenes=[_make_scene(prompt="V1")]))
    run(service.save_plan(run_id=301, scenes=[_make_scene(prompt="V2")]))

    active = run(service.get_active_plan(301))

    assert active is not None
    assert active.version == 2
    assert active.scenes[0].prompt == "V2"


def test_get_active_plan_returns_none_for_missing(service: VisualPlanService) -> None:
    assert run(service.get_active_plan(9999)) is None


# -- list_plan_versions --------------------------------------------------------


def test_list_plan_versions_returns_newest_first(service: VisualPlanService) -> None:
    run(service.save_plan(run_id=401, scenes=[_make_scene(prompt="V1")]))
    run(service.save_plan(run_id=401, scenes=[_make_scene(prompt="V2")]))
    run(service.save_plan(run_id=401, scenes=[_make_scene(prompt="V3")]))

    plans = run(service.list_plan_versions(401))

    assert [p.version for p in plans] == [3, 2, 1]


def test_list_plan_versions_empty_for_missing(service: VisualPlanService) -> None:
    assert run(service.list_plan_versions(9999)) == []


# -- Concurrent saves ---------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_saves_produce_unique_versions() -> None:
    """Two concurrent saves for the same run_id must produce distinct versions."""
    storage = InMemoryVisualPlanStorage()
    svc = VisualPlanService(storage)

    results = await asyncio.gather(
        svc.save_plan(run_id=500, scenes=[_make_scene(prompt="A")]),
        svc.save_plan(run_id=500, scenes=[_make_scene(prompt="B")]),
    )

    versions = sorted(p.version for p in results)
    assert versions == [1, 2], f"Expected unique versions [1, 2], got {versions}"


@pytest.mark.asyncio
async def test_concurrent_saves_across_service_instances() -> None:
    """Two service instances sharing storage must still produce unique versions."""
    storage = InMemoryVisualPlanStorage()
    service_a = VisualPlanService(storage)
    service_b = VisualPlanService(storage)

    results = await asyncio.gather(
        service_a.save_plan(run_id=501, scenes=[_make_scene(prompt="A")]),
        service_b.save_plan(run_id=501, scenes=[_make_scene(prompt="B")]),
    )

    versions = sorted(p.version for p in results)
    assert versions == [1, 2], f"Expected unique versions [1, 2], got {versions}"


# -- Isolation between runs ----------------------------------------------------


def test_different_runs_have_independent_versions(service: VisualPlanService) -> None:
    run(service.save_plan(run_id=601, scenes=[_make_scene(prompt="Run601 V1")]))
    run(service.save_plan(run_id=602, scenes=[_make_scene(prompt="Run602 V1")]))
    run(service.save_plan(run_id=601, scenes=[_make_scene(prompt="Run601 V2")]))

    plan_601 = run(service.get_active_plan(601))
    plan_602 = run(service.get_active_plan(602))

    assert plan_601 is not None
    assert plan_601.version == 2
    assert plan_602 is not None
    assert plan_602.version == 1


# -- DataIntegrityError (malformed JSON) ---------------------------------------


def test_parse_scenes_raises_on_invalid_json(service: VisualPlanService) -> None:
    """Malformed JSON in scenes_json raises DataIntegrityError, not silent []."""
    storage = service.storage
    # Manually inject a corrupt row
    import asyncio as _aio

    async def _inject():
        plans = storage._plans.setdefault(700, [])
        plans.append({
            "id": 9000,
            "run_id": 700,
            "version": 1,
            "scenes_json": "{not valid json",
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        })

    _aio.run(_inject())

    with pytest.raises(DataIntegrityError, match="Malformed scenes_json"):
        run(service.get_active_plan(700))


def test_parse_scenes_raises_on_non_array_json(service: VisualPlanService) -> None:
    """scenes_json that is valid JSON but not an array raises DataIntegrityError."""
    storage = service.storage
    import asyncio as _aio

    async def _inject():
        plans = storage._plans.setdefault(701, [])
        plans.append({
            "id": 9001,
            "run_id": 701,
            "version": 1,
            "scenes_json": '{"not": "an array"}',
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        })

    _aio.run(_inject())

    with pytest.raises(DataIntegrityError, match="not a JSON array"):
        run(service.get_active_plan(701))


def test_parse_scenes_raises_on_invalid_scene_data(service: VisualPlanService) -> None:
    """scenes_json with array of invalid scene objects raises DataIntegrityError."""
    storage = service.storage
    import asyncio as _aio

    async def _inject():
        plans = storage._plans.setdefault(702, [])
        plans.append({
            "id": 9002,
            "run_id": 702,
            "version": 1,
            "scenes_json": '[{"missing": "required fields"}]',
            "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        })

    _aio.run(_inject())

    with pytest.raises(DataIntegrityError, match="Invalid scene data"):
        run(service.get_active_plan(702))
