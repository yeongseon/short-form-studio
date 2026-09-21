"""SF-60: deterministic AI replace-asset command builder.

build_replace_asset_proposal takes a caller-supplied CANDIDATE library asset id
and a target segment, and produces a valid CommandProposal (SF-55) that swaps the
segment's asset — but only after proving the candidate is real, workspace-scoped
authorized, same-project, and apply-compatible. It does NOT search or rank the
library; the candidate id comes from upstream (the UI/AI was shown the library),
and this builder authorizes it. It never invents inaccessible ids: an id that does
not resolve in the workspace (unknown or cross-workspace) is rejected as
unavailable with the same anti-enumeration message the applier uses, so a
cross-workspace id never leaks that it exists elsewhere.

Validation is delegated to the shared read-only applier path
(compute_proposal_diff), so the builder and Apply agree exactly on what is allowed
and there is a single source of truth for the replace rules (segment exists,
replacement resolves, same project, compatible media kind). The builder is
read-only over history; Apply/Cancel/Undo behave as for any accepted batch.
"""

from __future__ import annotations

from creator_domain.models import ReplaceAssetCommand

from creator_service.command_proposal import CommandProposal
from creator_service.editor_history import EditorHistory
from creator_service.proposal_diff import compute_proposal_diff


async def build_replace_asset_proposal(
    history: EditorHistory,
    *,
    segment_id: str,
    asset_id: int,
) -> CommandProposal:
    """Authorize a candidate asset and build a one-command replace proposal."""
    _, generation = await history.capture()
    proposal = CommandProposal(
        base_revision=generation,
        commands=[ReplaceAssetCommand(segment_id=segment_id, asset_id=asset_id)],
    )
    # Self-validate through the read-only applier so the builder rejects exactly
    # what Apply would (missing segment, unresolvable/cross-workspace/cross-project
    # asset, incompatible media kind); the raised ValidationError propagates and no
    # proposal is returned for an unauthorized candidate.
    await compute_proposal_diff(history, proposal)
    return proposal
