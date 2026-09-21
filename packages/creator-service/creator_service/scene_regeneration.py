"""SF-64: integrate scene-level regeneration with MediaAsset and the Timeline.

Scene regeneration itself — the versioned VisualAsset artifacts, the required
stage-review gate, and the task failure/cancel behavior — is already owned by the
generate_scene_image worker task and VisualAssetService; this module does NOT
re-run or reimplement them. It is the deterministic SELECTION-and-APPLY bridge:
given an already-regenerated asset chosen for a scene, it swaps every Timeline
segment belonging to that scene to the selected asset as ONE undoable batch through
the shared editor command history (SF-56), reusing the shared applier's validation
(SF-57/60) as the single source of truth. Unrelated scenes are preserved. A
regenerated VisualAsset version is bridged to the Timeline only after proving the
asset id it claims resolves in the workspace to a MediaAsset whose provenance
(visual_asset_id, scene_id, run_id) matches the supplied VisualAsset, so the
selection flows through the same workspace/project-scoped authorization the
compiler uses and a numeric id cannot be smuggled in.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from creator_domain.exceptions import ValidationError
from creator_domain.models import MediaAsset, ReplaceAssetCommand
from creator_domain.models.stage import RunStage
from creator_domain.models.visual_asset import VisualAsset

from creator_service.command_proposal import CommandProposal
from creator_service.editor_history import EditorHistory
from creator_service.proposal_diff import compute_proposal_diff


@runtime_checkable
class MediaAssetResolver(Protocol):
    """Resolves a workspace-scoped MediaAsset so the bridge can prove identity."""

    async def get_media_asset(self, asset_id: int, workspace_id: int) -> MediaAsset | None: ...

# The required stage-review gate for scene regeneration stays owned by the
# generate_scene_image worker task; this constant pins the reuse contract so the
# integration cannot silently fork the stages regeneration is allowed to run in.
SCENE_REGEN_ALLOWED_STAGES = frozenset(
    {
        RunStage.VISUAL_PLAN_REVIEW,
        RunStage.VISUAL_ASSET_GENERATING,
        RunStage.VISUAL_ASSET_REVIEW,
    }
)


async def build_scene_regeneration_proposal(
    history: EditorHistory,
    *,
    scene_id: str,
    asset_id: int,
) -> CommandProposal:
    """Select a regenerated asset for every segment of a scene as one undoable batch.

    A scene maps to one or more Timeline segments; this swaps each of them to the
    selected asset via a replaceAsset batch and self-validates the whole batch
    through the read-only applier (compute_proposal_diff), so an unresolvable,
    cross-workspace, cross-project, or media-kind-incompatible asset is rejected
    exactly as Apply would and nothing partially lands. Unrelated scenes are
    untouched. Read-only over history.
    """
    present, generation = await history.capture()
    segment_ids = [s.id for s in present.segments if s.scene_id == scene_id]
    if not segment_ids:
        raise ValidationError(f"no timeline segment belongs to scene {scene_id!r}")

    proposal = CommandProposal(
        base_revision=generation,
        commands=[
            ReplaceAssetCommand(segment_id=segment_id, asset_id=asset_id)
            for segment_id in segment_ids
        ],
    )
    await compute_proposal_diff(history, proposal)
    return proposal


async def select_scene_regeneration(
    history: EditorHistory,
    *,
    scene_id: str,
    visual_asset: VisualAsset,
    expected_run_id: int,
) -> CommandProposal:
    """Bridge a regenerated VisualAsset version onto a scene's Timeline segments.

    The VisualAsset must have been regenerated for this scene AND this editing
    session's run, and the asset id it claims must resolve in the workspace to a
    MediaAsset whose provenance (visual_asset_id, scene_id, run_id) matches the
    supplied VisualAsset — so a caller cannot smuggle a numeric id that collides
    with an unrelated authorized asset. Only after that identity proof is the
    selection applied through the same authorized path as
    build_scene_regeneration_proposal.
    """
    if visual_asset.scene_id != scene_id:
        raise ValidationError(
            f"visual asset was regenerated for scene {visual_asset.scene_id!r}, "
            f"not {scene_id!r}"
        )
    if visual_asset.run_id != expected_run_id:
        raise ValidationError(
            f"visual asset belongs to run {visual_asset.run_id}, "
            f"not the editing session's run {expected_run_id}"
        )

    resolver = history.asset_lookup
    if not isinstance(resolver, MediaAssetResolver):
        raise ValidationError(
            "asset resolver cannot verify visual-asset provenance for scene selection"
        )
    resolved = await resolver.get_media_asset(visual_asset.id, history.workspace_id)
    if resolved is None:
        raise ValidationError("replacement asset is unavailable")
    metadata = resolved.metadata
    if (
        metadata.get("visual_asset_id") != visual_asset.id
        or metadata.get("scene_id") != scene_id
        or resolved.run_id != visual_asset.run_id
    ):
        raise ValidationError(
            "resolved asset provenance does not match the regenerated visual asset"
        )

    return await build_scene_regeneration_proposal(
        history, scene_id=scene_id, asset_id=visual_asset.id
    )
