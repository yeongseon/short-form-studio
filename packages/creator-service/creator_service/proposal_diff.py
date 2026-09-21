"""SF-57: read-only before/after diff for an untrusted AI command proposal.

compute_proposal_diff previews what an AI CommandProposal (SF-55) WOULD do to the
Timeline WITHOUT mutating EditorHistory. It captures an atomic (present,
generation) snapshot from the history, revalidates the proposal's base_revision
against that generation the SAME way Apply does (stale -> VersionConflictError),
then folds every command through the shared applier on the captured copy. Any
command the applier rejects (unknown target, cross-workspace asset, invalid
timing, or a not-applicable style/audio/output command) raises the SAME
ValidationError Apply would, so Preview and Apply agree on validity — a proposal
that cannot be applied is never previewed as if it could.

The result is a structural segment diff (added / removed / modified by segment id)
plus total-duration before/after, labeled with the captured base_revision. Style,
audio, and output-preset commands are NOT applicable to the Timeline in the merged
domain (the applier rejects them), so they cannot appear in a valid proposal and
are not represented here; before/after for those belongs to a separate
RenderPlan/output-preset domain, not this Timeline diff.
"""

from __future__ import annotations

from typing import ClassVar

from creator_domain.exceptions import VersionConflictError
from creator_domain.models import MediaSegment, Timeline
from pydantic import BaseModel, ConfigDict, Field

from creator_service.command_proposal import CommandProposal
from creator_service.editor_command_applier import apply_editor_command
from creator_service.editor_history import EditorHistory


class SegmentFieldChange(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    field: str
    before: object
    after: object


class ModifiedSegment(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    segment_id: str
    changes: list[SegmentFieldChange]


class ProposalDiff(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    base_revision: int = Field(ge=0)
    added: list[MediaSegment] = Field(default_factory=list)
    removed: list[MediaSegment] = Field(default_factory=list)
    modified: list[ModifiedSegment] = Field(default_factory=list)
    total_duration_before: float = Field(ge=0)
    total_duration_after: float = Field(ge=0)


_DIFFED_FIELDS = (
    "scene_id",
    "asset_id",
    "timeline_start_seconds",
    "duration_seconds",
    "trim_start_seconds",
    "trim_end_seconds",
    "fit_mode",
    "transition",
)


def _diff_segment(before: MediaSegment, after: MediaSegment) -> ModifiedSegment | None:
    changes = [
        SegmentFieldChange(
            field=field,
            before=getattr(before, field),
            after=getattr(after, field),
        )
        for field in _DIFFED_FIELDS
        if getattr(before, field) != getattr(after, field)
    ]
    if not changes:
        return None
    return ModifiedSegment(segment_id=after.id, changes=changes)


def _build_diff(before: Timeline, after: Timeline, *, base_revision: int) -> ProposalDiff:
    before_by_id = {s.id: s for s in before.segments}
    after_by_id = {s.id: s for s in after.segments}

    added = [s for s in after.segments if s.id not in before_by_id]
    removed = [s for s in before.segments if s.id not in after_by_id]
    modified: list[ModifiedSegment] = []
    for after_seg in after.segments:
        before_seg = before_by_id.get(after_seg.id)
        if before_seg is None:
            continue
        change = _diff_segment(before_seg, after_seg)
        if change is not None:
            modified.append(change)

    return ProposalDiff(
        base_revision=base_revision,
        added=added,
        removed=removed,
        modified=modified,
        total_duration_before=before.total_duration_seconds,
        total_duration_after=after.total_duration_seconds,
    )


async def compute_proposal_diff(
    history: EditorHistory,
    proposal: CommandProposal,
) -> ProposalDiff:
    """Preview a proposal's before/after structural diff without mutating history."""
    before, generation = await history.capture()
    if proposal.base_revision != generation:
        raise VersionConflictError(before.project_id, proposal.base_revision, generation)

    working = before
    for command in proposal.commands:
        working = await apply_editor_command(
            working,
            command,
            workspace_id=history.workspace_id,
            base_revision=working.revision,
            asset_lookup=history.asset_lookup,
        )

    return _build_diff(before, working, base_revision=generation)
