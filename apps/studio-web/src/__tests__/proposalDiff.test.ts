import { describe, it, expect } from "vitest";
import {
  summarizeProposalDiff,
  type ProposalDiff,
  type DiffSegment,
} from "../components/creator/proposalDiff";

function segment(overrides: Partial<DiffSegment> = {}): DiffSegment {
  return {
    id: "s1",
    scene_id: "scene-1",
    asset_id: 10,
    timeline_start_seconds: 0,
    duration_seconds: 4,
    trim_start_seconds: 0,
    trim_end_seconds: 4,
    fit_mode: "cover",
    transition: null,
    ...overrides,
  };
}

function diff(overrides: Partial<ProposalDiff> = {}): ProposalDiff {
  return {
    base_revision: 3,
    added: [],
    removed: [],
    modified: [],
    total_duration_before: 7,
    total_duration_after: 7,
    ...overrides,
  };
}

describe("summarizeProposalDiff", () => {
  it("counts added, removed, and modified segments", () => {
    const summary = summarizeProposalDiff(
      diff({
        added: [segment({ id: "s3" })],
        removed: [segment({ id: "s2" })],
        modified: [
          {
            segment_id: "s1",
            changes: [{ field: "asset_id", before: 10, after: 12 }],
          },
        ],
      }),
    );
    expect(summary.addedCount).toBe(1);
    expect(summary.removedCount).toBe(1);
    expect(summary.modifiedCount).toBe(1);
    expect(summary.hasChanges).toBe(true);
  });

  it("reports no changes for an empty structural diff", () => {
    const summary = summarizeProposalDiff(diff());
    expect(summary.hasChanges).toBe(false);
    expect(summary.addedCount).toBe(0);
    expect(summary.removedCount).toBe(0);
    expect(summary.modifiedCount).toBe(0);
  });

  it("carries the base revision through for staleness labeling", () => {
    expect(summarizeProposalDiff(diff({ base_revision: 5 })).baseRevision).toBe(5);
  });

  it("computes the total-duration delta (negative when the edit shortens)", () => {
    const summary = summarizeProposalDiff(
      diff({ total_duration_before: 7, total_duration_after: 2 }),
    );
    expect(summary.durationBefore).toBe(7);
    expect(summary.durationAfter).toBe(2);
    expect(summary.durationDelta).toBe(-5);
  });

  it("computes a positive delta when the edit lengthens", () => {
    const summary = summarizeProposalDiff(
      diff({ total_duration_before: 7, total_duration_after: 9 }),
    );
    expect(summary.durationDelta).toBe(2);
  });
});
