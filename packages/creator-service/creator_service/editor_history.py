"""SF-49/50: Undo and Redo for accepted editor changes.

EditorHistory wraps ``apply_editor_command`` and records the pre-command Timeline
snapshot ONLY when a command (or an accepted batch of commands) succeeds, so a
failed command never enters history. ``undo`` restores the exact prior snapshot
and moves the current state onto a redo (future) stack; ``redo`` deterministically
replays the last undone change. Any new accepted edit clears the redo branch, so
redo never replays a change a later edit diverged from. A batch — e.g. an accepted
AI edit — is applied atomically and recorded as one undo/redo step, so undo/redo
revert or replay the whole batch. Manual single commands and accepted AI batches
therefore undo/redo consistently.
"""

from __future__ import annotations

from collections.abc import Sequence

from creator_domain.exceptions import NoHistoryError, ValidationError
from creator_domain.models import Timeline

from creator_service.editor_command_applier import (
    EditorAssetLookup,
    apply_editor_command,
)


class EditorHistory:
    def __init__(
        self,
        timeline: Timeline,
        *,
        workspace_id: int,
        asset_lookup: EditorAssetLookup,
    ) -> None:
        self._present = timeline
        self._workspace_id = workspace_id
        self._asset_lookup = asset_lookup
        self._past: list[Timeline] = []
        self._future: list[Timeline] = []

    @property
    def present(self) -> Timeline:
        return self._present

    @property
    def can_undo(self) -> bool:
        return len(self._past) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._future) > 0

    async def apply(self, command: object) -> Timeline:
        """Apply one command; record the prior snapshot only on success."""
        result = await apply_editor_command(
            self._present,
            command,
            workspace_id=self._workspace_id,
            base_revision=self._present.revision,
            asset_lookup=self._asset_lookup,
        )
        self._past.append(self._present.model_copy(deep=True))
        self._present = result
        self._future.clear()
        return result

    async def apply_batch(self, commands: Sequence[object]) -> Timeline:
        """Apply commands atomically as one undoable step.

        The batch is applied against a working copy; if any command fails the
        whole batch is discarded and history is untouched (the accepted AI edit
        never partially lands). On success a single prior snapshot is recorded.
        An empty batch is not an accepted change, so it is rejected rather than
        recording a no-op undo boundary.
        """
        if not commands:
            raise ValidationError("cannot apply an empty command batch")
        working = self._present
        for command in commands:
            working = await apply_editor_command(
                working,
                command,
                workspace_id=self._workspace_id,
                base_revision=working.revision,
                asset_lookup=self._asset_lookup,
            )
        self._past.append(self._present.model_copy(deep=True))
        self._present = working
        self._future.clear()
        return working

    def undo(self) -> Timeline:
        """Restore the prior snapshot; move the current state onto the redo stack."""
        if not self._past:
            raise NoHistoryError("nothing to undo")
        self._future.append(self._present.model_copy(deep=True))
        self._present = self._past.pop()
        return self._present

    def redo(self) -> Timeline:
        """Deterministically replay the last undone change."""
        if not self._future:
            raise NoHistoryError("nothing to redo")
        self._past.append(self._present.model_copy(deep=True))
        self._present = self._future.pop()
        return self._present
