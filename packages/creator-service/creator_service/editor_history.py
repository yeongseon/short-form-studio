"""SF-49: Undo for accepted editor changes.

EditorHistory wraps ``apply_editor_command`` and records the pre-command Timeline
snapshot ONLY when a command (or an accepted batch of commands) succeeds, so a
failed command never enters history. ``undo`` restores the exact prior snapshot.
A batch — e.g. an accepted AI edit — is applied atomically and recorded as one
undoable step, so undoing it reverts the whole batch. Manual single commands and
accepted AI batches therefore undo consistently.
"""

from __future__ import annotations

from collections.abc import Sequence

from creator_domain.exceptions import NoHistoryError
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

    @property
    def present(self) -> Timeline:
        return self._present

    @property
    def can_undo(self) -> bool:
        return len(self._past) > 0

    async def apply(self, command: object) -> Timeline:
        """Apply one command; record the prior snapshot only on success."""
        result = await apply_editor_command(
            self._present,
            command,
            workspace_id=self._workspace_id,
            base_revision=self._present.revision,
            asset_lookup=self._asset_lookup,
        )
        self._past.append(self._present)
        self._present = result
        return result

    async def apply_batch(self, commands: Sequence[object]) -> Timeline:
        """Apply commands atomically as one undoable step.

        The batch is applied against a working copy; if any command fails the
        whole batch is discarded and history is untouched (the accepted AI edit
        never partially lands). On success a single prior snapshot is recorded.
        """
        working = self._present
        for command in commands:
            working = await apply_editor_command(
                working,
                command,
                workspace_id=self._workspace_id,
                base_revision=working.revision,
                asset_lookup=self._asset_lookup,
            )
        self._past.append(self._present)
        self._present = working
        return working

    def undo(self) -> Timeline:
        """Restore the exact snapshot before the last accepted change."""
        if not self._past:
            raise NoHistoryError("nothing to undo")
        self._present = self._past.pop()
        return self._present
