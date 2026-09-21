"""SF-49/50/56: Undo, Redo, and edit-generation for accepted editor changes.

EditorHistory wraps ``apply_editor_command`` and records the pre-command Timeline
snapshot ONLY when a command (or an accepted batch of commands) succeeds, so a
failed command never enters history. ``undo`` restores the exact prior snapshot
and moves the current state onto a redo (future) stack; ``redo`` deterministically
replays the last undone change. Any new accepted edit clears the redo branch, so
redo never replays a change a later edit diverged from. A batch — e.g. an accepted
AI edit — is applied atomically and recorded as one undo/redo step, so undo/redo
revert or replay the whole batch. Manual single commands and accepted AI batches
therefore undo/redo consistently.

``generation`` is a session-local edit epoch, distinct from ``Timeline.revision``
(which stays the persistence optimistic-concurrency token owned by the save
layer). It starts at the loaded revision and advances on every accepted edit, and
undo/redo restore it alongside the snapshot. AI proposals carry the generation
they were built against so a proposal built before a later accepted edit is
detected as stale without disturbing the persisted revision.

ALL state mutations (apply, apply_batch, undo, redo, and the generation-checked
proposal path) serialize through one ``asyncio.Lock``, so a mutation that awaits
mid-way (e.g. an asset lookup) cannot be interleaved by another mutation on the
same history — the history is a single consistent critical section.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from creator_domain.exceptions import NoHistoryError, ValidationError, VersionConflictError
from creator_domain.models import Timeline

from creator_service.editor_command_applier import (
    EditorAssetLookup,
    apply_editor_command,
)


@dataclass(frozen=True)
class _HistoryEntry:
    timeline: Timeline
    generation: int


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
        self._generation = timeline.revision
        self._past: list[_HistoryEntry] = []
        self._future: list[_HistoryEntry] = []
        self._lock = asyncio.Lock()

    @property
    def present(self) -> Timeline:
        return self._present

    @property
    def workspace_id(self) -> int:
        return self._workspace_id

    @property
    def asset_lookup(self) -> EditorAssetLookup:
        return self._asset_lookup

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def can_undo(self) -> bool:
        return len(self._past) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._future) > 0

    async def apply(self, command: object) -> Timeline:
        """Apply one command; record the prior snapshot only on success."""
        async with self._lock:
            return await self._apply_unlocked(command)

    async def apply_batch(self, commands: Sequence[object]) -> Timeline:
        """Apply commands atomically as one undoable step."""
        async with self._lock:
            return await self._apply_batch_unlocked(commands)

    async def apply_batch_if_generation(
        self, commands: Sequence[object], *, expected_generation: int
    ) -> Timeline:
        """Atomically check the generation and apply a batch as one critical section.

        The generation check, the batch application, and the generation increment
        are serialized under the lock, so two concurrent proposals built against
        the same generation cannot both pass the check and double-apply — exactly
        one succeeds and the other is rejected as stale — and no other history
        mutation can interleave mid-application.
        """
        async with self._lock:
            if expected_generation != self._generation:
                raise VersionConflictError(
                    self._present.project_id, expected_generation, self._generation
                )
            return await self._apply_batch_unlocked(commands)

    async def capture(self) -> tuple[Timeline, int]:
        # Read-only atomic snapshot of (present, generation) for a dry-run
        # preview: a deep copy is returned under the lock so the caller can
        # fold commands over an immutable timeline without a concurrent mutation
        # moving present/generation mid-read. History itself is NOT mutated.
        async with self._lock:
            return self._present.model_copy(deep=True), self._generation

    async def undo(self) -> Timeline:
        """Restore the prior snapshot; move the current state onto the redo stack."""
        async with self._lock:
            if not self._past:
                raise NoHistoryError("nothing to undo")
            self._future.append(self._snapshot())
            entry = self._past.pop()
            self._present = entry.timeline
            self._generation = entry.generation
            return self._present

    async def redo(self) -> Timeline:
        """Deterministically replay the last undone change."""
        async with self._lock:
            if not self._future:
                raise NoHistoryError("nothing to redo")
            self._past.append(self._snapshot())
            entry = self._future.pop()
            self._present = entry.timeline
            self._generation = entry.generation
            return self._present

    async def _apply_unlocked(self, command: object) -> Timeline:
        result = await apply_editor_command(
            self._present,
            command,
            workspace_id=self._workspace_id,
            base_revision=self._present.revision,
            asset_lookup=self._asset_lookup,
        )
        self._past.append(self._snapshot())
        self._present = result
        self._generation += 1
        self._future.clear()
        return result

    async def _apply_batch_unlocked(self, commands: Sequence[object]) -> Timeline:
        # The batch is applied against a working copy; if any command fails the
        # whole batch is discarded and history is untouched (never partially
        # lands). On success a single prior snapshot is recorded. An empty batch
        # is not an accepted change, so it is rejected.
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
        self._past.append(self._snapshot())
        self._present = working
        self._generation += 1
        self._future.clear()
        return working

    def _snapshot(self) -> _HistoryEntry:
        return _HistoryEntry(
            timeline=self._present.model_copy(deep=True), generation=self._generation
        )
