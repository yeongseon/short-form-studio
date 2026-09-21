"""SF-60: deterministic AI replace-asset command builder.

build_replace_asset_proposal takes a caller-supplied CANDIDATE library asset id
and a target segment, and produces a valid CommandProposal (SF-55) that swaps the
segment's asset — but only after proving the candidate is real, workspace-scoped
authorized, same-project, and apply-compatible. It does NOT search or rank the
library; the candidate id comes from upstream (UI/AI shown the library), and this
builder authorizes it. It never invents inaccessible ids: an id that does not
resolve in the workspace (unknown or cross-workspace) is rejected as unavailable
with the same anti-enumeration message the applier uses, so a cross-workspace id
never leaks that it exists elsewhere. Validation is delegated to the shared
read-only applier path (compute_proposal_diff), so the builder and Apply agree
exactly on what is allowed. The builder is read-only over history; Apply/Cancel/
Undo behave as for any accepted batch.
"""

from __future__ import annotations

import pytest
from creator_domain.exceptions import ValidationError
from creator_domain.models import ReplaceAssetCommand, Timeline
from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import EditorAssetRef
from creator_service.editor_history import EditorHistory
from creator_service.replace_asset_proposal import build_replace_asset_proposal
from creator_service.validate_ai_proposal import apply_ai_proposal


class _FakeAssetLookup:
    # Workspace-scoped resolver: a workspace_id mismatch resolves to None, exactly
    # like the real lookup, so cross-workspace assets are indistinguishable from
    # unknown ones (anti-enumeration).
    def __init__(self, assets: dict[int, EditorAssetRef], *, workspace_id: int = 1) -> None:
        self._assets = assets
        self._workspace_id = workspace_id

    async def get_asset_for_editor(
        self, asset_id: int, workspace_id: int
    ) -> EditorAssetRef | None:
        if workspace_id != self._workspace_id:
            return None
        return self._assets.get(asset_id)


def _video(asset_id: int, *, project_id: int = 1, duration_seconds: float = 60.0) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id, project_id=project_id, media_type="VIDEO", duration_seconds=duration_seconds
    )


def _image(asset_id: int, *, project_id: int = 1) -> EditorAssetRef:
    return EditorAssetRef(
        id=asset_id, project_id=project_id, media_type="IMAGE", duration_seconds=0.0
    )


def _timeline() -> Timeline:
    return Timeline.model_validate(
        {
            "id": "tl-1",
            "project_id": 1,
            "revision": 3,
            "segments": [
                {
                    "id": "s1",
                    "scene_id": "scene-1",
                    "asset_id": 10,
                    "timeline_start_seconds": 0.0,
                    "duration_seconds": 4.0,
                    "trim_start_seconds": 0.0,
                    "trim_end_seconds": 4.0,
                }
            ],
        }
    )


def _history(assets: dict[int, EditorAssetRef]) -> EditorHistory:
    return EditorHistory(_timeline(), workspace_id=1, asset_lookup=_FakeAssetLookup(assets))


@pytest.mark.asyncio
async def test_proposes_replacement_with_authorized_compatible_asset() -> None:
    h = _history({10: _video(10), 20: _video(20)})
    proposal = await build_replace_asset_proposal(h, segment_id="s1", asset_id=20)
    assert isinstance(proposal, CommandProposal)
    assert proposal.base_revision == 3
    assert len(proposal.commands) == 1
    command = proposal.commands[0]
    assert isinstance(command, ReplaceAssetCommand)
    assert command.segment_id == "s1"
    assert command.asset_id == 20


@pytest.mark.asyncio
async def test_builder_is_read_only() -> None:
    h = _history({10: _video(10), 20: _video(20)})
    before = h.present.model_dump(mode="json")
    await build_replace_asset_proposal(h, segment_id="s1", asset_id=20)
    assert h.present.model_dump(mode="json") == before
    assert h.generation == 3
    assert h.can_undo is False


@pytest.mark.asyncio
async def test_apply_then_undo_round_trip() -> None:
    h = _history({10: _video(10), 20: _video(20)})
    original = h.present.model_dump(mode="json")
    proposal = await build_replace_asset_proposal(h, segment_id="s1", asset_id=20)

    applied = await apply_ai_proposal(h, proposal)
    assert applied.segments[0].asset_id == 20
    assert h.generation == 4

    reverted = await h.undo()
    assert reverted.model_dump(mode="json") == original
    assert reverted.segments[0].asset_id == 10
    assert h.generation == 3


@pytest.mark.asyncio
async def test_rejects_an_unknown_invented_asset_id() -> None:
    h = _history({10: _video(10)})
    with pytest.raises(ValidationError, match="unavailable"):
        await build_replace_asset_proposal(h, segment_id="s1", asset_id=999)
    assert h.generation == 3
    assert h.can_undo is False


@pytest.mark.asyncio
async def test_rejects_a_cross_workspace_asset_as_unavailable() -> None:
    # asset 30 exists, but only resolvable in workspace 2; this history is
    # workspace 1, so the lookup returns None and the id is rejected without
    # revealing it exists elsewhere.
    lookup = _FakeAssetLookup({10: _video(10), 30: _video(30)}, workspace_id=2)
    h = EditorHistory(_timeline(), workspace_id=1, asset_lookup=lookup)
    with pytest.raises(ValidationError, match="unavailable"):
        await build_replace_asset_proposal(h, segment_id="s1", asset_id=30)


@pytest.mark.asyncio
async def test_rejects_a_same_workspace_cross_project_asset() -> None:
    h = _history({10: _video(10), 40: _video(40, project_id=2)})
    with pytest.raises(ValidationError, match="unavailable"):
        await build_replace_asset_proposal(h, segment_id="s1", asset_id=40)


@pytest.mark.asyncio
async def test_rejects_an_incompatible_media_kind() -> None:
    # s1 is a video segment; replacing with an image asset is rejected.
    h = _history({10: _video(10), 50: _image(50)})
    with pytest.raises(ValidationError, match="media kind is incompatible"):
        await build_replace_asset_proposal(h, segment_id="s1", asset_id=50)


@pytest.mark.asyncio
async def test_rejects_a_missing_segment() -> None:
    h = _history({10: _video(10), 20: _video(20)})
    with pytest.raises(ValidationError, match="segment not found"):
        await build_replace_asset_proposal(h, segment_id="ghost", asset_id=20)
