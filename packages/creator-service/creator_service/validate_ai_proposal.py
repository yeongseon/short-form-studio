"""SF-56: validate AI command proposals through the shared editor boundary.

apply_ai_proposal treats a CommandProposal (SF-55) as untrusted. At Apply it
REVALIDATES the proposal's base_revision against the history's current edit
generation (a session-local epoch that advances on every accepted edit, distinct
from the persisted Timeline.revision), so a proposal generated before a later
accepted edit is rejected as stale before anything runs. It then applies the
command batch atomically through EditorHistory.apply_batch, which validates every
command's type, target, ownership, and timings via the shared applier and lands
the whole batch or none of it. A rejected proposal leaves the timeline unmutated
and does not enter history — nothing is applied before validation passes.
"""

from __future__ import annotations

from creator_domain.exceptions import VersionConflictError
from creator_domain.models import Timeline

from creator_service.command_proposal import CommandProposal
from creator_service.editor_history import EditorHistory


async def apply_ai_proposal(
    history: EditorHistory,
    proposal: CommandProposal,
) -> Timeline:
    """Revalidate and apply an untrusted AI proposal atomically at Apply time.

    Asset ownership and workspace scoping are enforced by the EditorHistory the
    proposal is applied to (its workspace_id drives the per-command validation),
    so this function does not take a separate workspace_id — the history is the
    trust boundary. Staleness is checked against the history's edit generation,
    not the persisted revision.
    """
    if proposal.base_revision != history.generation:
        raise VersionConflictError(
            history.present.project_id, proposal.base_revision, history.generation
        )
    return await history.apply_batch(proposal.commands)
