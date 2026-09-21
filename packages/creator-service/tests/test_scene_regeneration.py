"""SF-64: integrate scene-level regeneration with MediaAsset and the Timeline.

Scene regeneration itself (the versioned VisualAsset artifacts, the required
stage-review gate, and the task failure/cancel behavior) is already owned by the
generate_scene_image worker task and VisualAssetService — this module does NOT
re-run or reimplement them. It is the deterministic SELECTION-and-APPLY bridge:
given an already-regenerated asset chosen for a scene, it swaps every Timeline
segment belonging to that scene to the selected asset as ONE undoable batch through
the shared editor command history (SF-56), reusing the shared applier's validation
(SF-57/60) as the single source of truth. Unrelated scenes are preserved. A
VisualAsset version is bridged to a MediaAsset via the existing
MediaAsset.from_visual_asset adapter, so the selection flows through the same
workspace/project-scoped authorization the compiler uses.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import (
    MediaAsset,
    MediaOrigin,
    MediaType,
    Timeline,
)
from creator_domain.models.visual_asset import VisualAsset
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.proposal_diff import compute_proposal_diff
from creator_service.scene_regeneration import (
    build_scene_regeneration_proposal,
    select_scene_regeneration,
)
from creator_service.validate_ai_proposal import apply_ai_proposal


class _FakeAssetLookup:
    def __init__(self, assets: dict[int, EditorAssetRef], *, workspace_id: int = 1) -> None:
        self._assets = assets
        self._workspace_id = workspace_id

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        if workspace_id != self._workspace_id:
            return None
        return self._assets.get(asset_id)


def _image(asset_id: int, *, project_id: int = 1) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id, project_id=project_id, media_type="IMAGE", duration_seconds=0.0
    )


def _seg(seg_id: str, scene_id: str, start: float, asset_id: int) -> dict[str, object]:
    return {
        "id": seg_id,
        "scene_id": scene_id,
        "asset_id": asset_id,
        "timeline_start_seconds": start,
        "duration_seconds": 4.0,
    }


def _timeline() -> Timeline:
    # Two scenes: scene-A has s1+s2 (both asset 10), scene-B has s3 (asset 11).
    return Timeline.model_validate(
        {
            "id": "tl-1",
            "project_id": 1,
            "revision": 3,
            "segments": [
                _seg("s1", "scene-A", 0.0, 10),
                _seg("s2", "scene-A", 4.0, 10),
                _seg("s3", "scene-B", 8.0, 11),
            ],
        }
    )


def _history(assets: dict[int, EditorAssetRef]) -> EditorHistory:
    return EditorHistory(_timeline(), workspace_id=1, asset_lookup=_FakeAssetLookup(assets))


# ------------------------- pure core: per-scene batch selection -------------------------


@pytest.mark.asyncio
async def test_selects_a_regenerated_asset_for_every_segment_of_a_scene() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20)})
    proposal = await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=20)
    assert proposal.base_revision == 3
    # one replaceAsset per segment in scene-A (s1, s2), none for scene-B (s3)
    assert len(proposal.commands) == 2
    assert {c.segment_id for c in proposal.commands} == {"s1", "s2"}
    assert all(c.asset_id == 20 for c in proposal.commands)


@pytest.mark.asyncio
async def test_preserves_unrelated_scenes() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20)})
    proposal = await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=20)
    diff = await compute_proposal_diff(h, proposal)
    # only scene-A segments change, and only their asset_id
    assert {m.segment_id for m in diff.modified} == {"s1", "s2"}
    for modified in diff.modified:
        assert {c.field for c in modified.changes} == {"asset_id"}
    assert diff.removed == []
    assert diff.added == []


@pytest.mark.asyncio
async def test_selection_is_one_undoable_batch_restoring_every_segment() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20)})
    original = h.present.model_dump(mode="json")
    proposal = await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=20)

    applied = await apply_ai_proposal(h, proposal)
    assert [s.asset_id for s in applied.segments if s.scene_id == "scene-A"] == [20, 20]
    assert [s.asset_id for s in applied.segments if s.scene_id == "scene-B"] == [11]
    assert h.generation == 4

    reverted = await h.undo()
    assert reverted.model_dump(mode="json") == original
    assert h.generation == 3


@pytest.mark.asyncio
async def test_builder_is_read_only() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20)})
    before = h.present.model_dump(mode="json")
    await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=20)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3
    assert h.can_undo is False


@pytest.mark.asyncio
async def test_rejects_a_scene_with_no_matching_segments() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20)})
    with pytest.raises(ValidationError, match="scene"):
        await build_scene_regeneration_proposal(h, scene_id="scene-Z", asset_id=20)


@pytest.mark.asyncio
async def test_rejects_a_cross_workspace_asset_as_unavailable() -> None:
    lookup = _FakeAssetLookup({10: _image(10), 11: _image(11), 30: _image(30)}, workspace_id=2)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)
    with pytest.raises(ValidationError, match="unavailable"):
        await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=30)


@pytest.mark.asyncio
async def test_rejects_a_cross_project_asset() -> None:
    h = _history({10: _image(10), 11: _image(11), 40: _image(40, project_id=2)})
    with pytest.raises(ValidationError, match="unavailable"):
        await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=40)


@pytest.mark.asyncio
async def test_rejects_an_incompatible_media_kind_atomically() -> None:
    # scene-A segments are image; replacing with a video asset is rejected, and
    # because it is one batch, NOTHING lands (all-or-nothing).
    video = EditorAssetRef(id=50, project_id=1, media_type="VIDEO", duration_seconds=30.0)
    h = _history({10: _image(10), 11: _image(11), 50: video})
    before = h.present.model_dump(mode="json")
    with pytest.raises(ValidationError, match="media kind is incompatible"):
        await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=50)
    assert h.present.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_rejects_an_unknown_asset() -> None:
    h = _history({10: _image(10), 11: _image(11)})
    with pytest.raises(ValidationError, match="unavailable"):
        await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=999)


# ------------------------- versioned selection: two versions undo independently -------------------------


@pytest.mark.asyncio
async def test_selecting_a_second_version_is_a_separate_undoable_step() -> None:
    h = _history({10: _image(10), 11: _image(11), 20: _image(20), 21: _image(21)})
    first = await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=20)
    await apply_ai_proposal(h, first)
    assert h.generation == 4

    second = await build_scene_regeneration_proposal(h, scene_id="scene-A", asset_id=21)
    applied = await apply_ai_proposal(h, second)
    assert [s.asset_id for s in applied.segments if s.scene_id == "scene-A"] == [21, 21]
    assert h.generation == 5

    # undo returns to the first selection (version 20), not the original
    reverted = await h.undo()
    assert [s.asset_id for s in reverted.segments if s.scene_id == "scene-A"] == [20, 20]


# ------------------------- VisualAsset -> MediaAsset bridge -------------------------


def _visual(asset_id: int, scene_id: str, *, version: int) -> VisualAsset:
    return VisualAsset(
        id=asset_id,
        run_id=7,
        scene_id=scene_id,
        version=version,
        asset_path=f"assets/{asset_id}.png",
        storage_key=f"assets/{asset_id}.png",
        is_active=True,
        created_at=datetime.now(UTC),
    )


class _MediaAssetLookup:
    # Resolver that is visual-asset provenance aware: it exposes both the editor
    # ref (for the applier) and the resolved MediaAsset (for the bridge's identity
    # proof), so the bridge can confirm the resolved asset IS the selected visual.
    def __init__(self, assets: dict[int, MediaAsset], *, workspace_id: int) -> None:
        self._assets = assets
        self._workspace_id = workspace_id

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        if workspace_id != self._workspace_id:
            return None
        asset = self._assets.get(asset_id)
        if asset is None or asset.project_id != 1:
            return None
        return EditorAssetRef(
            id=asset.id,
            project_id=asset.project_id or 1,
            media_type=asset.media_type.value,
            duration_seconds=asset.duration_seconds or 0.0,
        )

    async def get_media_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None:
        if workspace_id != self._workspace_id:
            return None
        return self._assets.get(asset_id)


@pytest.mark.asyncio
async def test_bridges_a_regenerated_visual_asset_to_a_selectable_media_asset() -> None:
    # A regenerated VisualAsset version is adapted to a MediaAsset (preserving its
    # id) and selected onto the scene through the same authorized apply path.
    visual = _visual(20, "scene-A", version=2)
    media = MediaAsset.from_visual_asset(visual, workspace_id=1, project_id=1)
    lookup = _MediaAssetLookup({20: media}, workspace_id=1)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)

    proposal = await select_scene_regeneration(
        h, scene_id="scene-A", visual_asset=visual, expected_run_id=7
    )
    assert {c.segment_id for c in proposal.commands} == {"s1", "s2"}
    assert all(c.asset_id == 20 for c in proposal.commands)


@pytest.mark.asyncio
async def test_bridge_rejects_a_visual_asset_for_a_different_scene() -> None:
    visual = _visual(20, "scene-OTHER", version=1)
    media = MediaAsset.from_visual_asset(visual, workspace_id=1, project_id=1)
    lookup = _MediaAssetLookup({20: media}, workspace_id=1)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)
    with pytest.raises(ValidationError, match="scene"):
        await select_scene_regeneration(
            h, scene_id="scene-A", visual_asset=visual, expected_run_id=7
        )


@pytest.mark.asyncio
async def test_bridge_rejects_a_visual_asset_from_a_different_run() -> None:
    # A VisualAsset from run 8 cannot be selected into a run-7 editing session even
    # if its numeric id happens to resolve to an authorized asset.
    visual = _visual(20, "scene-A", version=1)
    object.__setattr__(visual, "run_id", 8)
    media = MediaAsset.from_visual_asset(visual, workspace_id=1, project_id=1)
    lookup = _MediaAssetLookup({20: media}, workspace_id=1)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)
    with pytest.raises(ValidationError, match="run"):
        await select_scene_regeneration(
            h, scene_id="scene-A", visual_asset=visual, expected_run_id=7
        )


@pytest.mark.asyncio
async def test_bridge_rejects_an_id_collision_with_an_unrelated_media_asset() -> None:
    # The caller supplies VisualAsset id 20, but id 20 in the workspace resolves to
    # an unrelated MediaAsset (no matching visual_asset_id provenance). The bridge
    # must reject rather than trust the numeric id.
    unrelated = MediaAsset(
        id=20,
        workspace_id=1,
        project_id=1,
        media_type=MediaType.IMAGE,
        origin=MediaOrigin.UPLOADED,
        storage_key="assets/unrelated.png",
        created_at=datetime.now(UTC),
    )
    lookup = _MediaAssetLookup({20: unrelated}, workspace_id=1)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)
    visual = _visual(20, "scene-A", version=1)
    with pytest.raises(ValidationError, match="provenance|does not match|regenerated"):
        await select_scene_regeneration(
            h, scene_id="scene-A", visual_asset=visual, expected_run_id=7
        )


# ------------------------- reuse characterization: existing worker regeneration -------------------------


def test_reuses_the_existing_scene_regeneration_worker_stage_gate() -> None:
    # SF-64 does not reimplement regeneration: the required stage-review gate and
    # task failure/cancel behavior remain owned by generate_scene_image, whose
    # TaskRunnerConfig restricts execution to the visual-review stages. This pins
    # that reuse contract so the integration cannot silently fork the gate.
    from creator_domain.models.stage import RunStage
    from creator_service.scene_regeneration import SCENE_REGEN_ALLOWED_STAGES

    assert SCENE_REGEN_ALLOWED_STAGES == frozenset(
        {
            RunStage.VISUAL_PLAN_REVIEW,
            RunStage.VISUAL_ASSET_GENERATING,
            RunStage.VISUAL_ASSET_REVIEW,
        }
    )
