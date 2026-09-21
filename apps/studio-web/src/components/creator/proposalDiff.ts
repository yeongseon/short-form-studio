/**
 * proposalDiff — pure view-model for the AI diff preview (SF-57).
 *
 * Mirrors the backend ProposalDiff (creator_service.proposal_diff): a structural
 * before/after of an AI CommandProposal against a known base_revision, with
 * segments added / removed / modified (per-field before/after) and total duration
 * before/after. This module NEVER mutates a timeline or calls apply — it turns the
 * backend diff into a display-ready summary the preview UI binds to, so Cancel is
 * simply discarding the summary and Apply is owned by the separate apply flow.
 *
 * Style, audio, and output-preset commands are not applicable to the Timeline in
 * the current domain (the backend applier rejects them), so a proposal containing
 * them is rejected before a diff exists; they are intentionally absent here.
 */

export interface SegmentFieldChange {
  field: string;
  before: unknown;
  after: unknown;
}

export interface ModifiedSegment {
  segment_id: string;
  changes: SegmentFieldChange[];
}

export interface DiffSegment {
  id: string;
  scene_id: string;
  asset_id: number;
  timeline_start_seconds: number;
  duration_seconds: number;
  trim_start_seconds: number | null;
  trim_end_seconds: number | null;
  fit_mode: string;
  transition: string | null;
}

export interface ProposalDiff {
  base_revision: number;
  added: DiffSegment[];
  removed: DiffSegment[];
  modified: ModifiedSegment[];
  total_duration_before: number;
  total_duration_after: number;
}

export interface ProposalDiffSummary {
  baseRevision: number;
  addedCount: number;
  removedCount: number;
  modifiedCount: number;
  hasChanges: boolean;
  durationBefore: number;
  durationAfter: number;
  durationDelta: number;
}

/**
 * Derive a display summary from a backend ProposalDiff. ``hasChanges`` is false
 * for an empty structural diff (a valid but no-op proposal), which the UI shows
 * as "no timeline changes" while still allowing Apply.
 */
export function summarizeProposalDiff(diff: ProposalDiff): ProposalDiffSummary {
  const addedCount = diff.added.length;
  const removedCount = diff.removed.length;
  const modifiedCount = diff.modified.length;
  return {
    baseRevision: diff.base_revision,
    addedCount,
    removedCount,
    modifiedCount,
    hasChanges: addedCount + removedCount + modifiedCount > 0,
    durationBefore: diff.total_duration_before,
    durationAfter: diff.total_duration_after,
    durationDelta: diff.total_duration_after - diff.total_duration_before,
  };
}
