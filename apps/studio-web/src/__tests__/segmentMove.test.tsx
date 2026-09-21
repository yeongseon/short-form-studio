import { describe, it, expect } from "vitest";
import {
  moveSegment,
  resequence,
  applyMove,
  createMoveHistory,
  undo,
  redo,
  type OrderedSegment,
  type MoveHistory,
} from "../components/creator/segmentMove";

function seg(id: string, dur: number, sceneId = "scene-1"): OrderedSegment {
  return { id, sceneId, durationSeconds: dur, timelineStartSeconds: 0 };
}

function track(): OrderedSegment[] {
  // resequenced: s1[0..2], s2[2..5], s3[5..9]
  return resequence([seg("s1", 2), seg("s2", 3), seg("s3", 4)]);
}

describe("resequence", () => {
  it("recomputes contiguous timeline positions with no gaps or overlaps", () => {
    const t = resequence([seg("a", 2), seg("b", 3), seg("c", 1)]);
    expect(t.map((s) => s.timelineStartSeconds)).toEqual([0, 2, 5]);
  });

  it("preserves order and ids", () => {
    const t = track();
    expect(t.map((s) => s.id)).toEqual(["s1", "s2", "s3"]);
  });
});

describe("moveSegment", () => {
  it("moves a segment to a later index and resequences", () => {
    const t = moveSegment(track(), "s1", 2);
    expect(t.map((s) => s.id)).toEqual(["s2", "s3", "s1"]);
    expect(t.map((s) => s.timelineStartSeconds)).toEqual([0, 3, 7]);
  });

  it("moves a segment to an earlier index and resequences", () => {
    const t = moveSegment(track(), "s3", 0);
    expect(t.map((s) => s.id)).toEqual(["s3", "s1", "s2"]);
    expect(t.map((s) => s.timelineStartSeconds)).toEqual([0, 4, 6]);
  });

  it("moving to the first index is valid (first move)", () => {
    const t = moveSegment(track(), "s2", 0);
    expect(t.map((s) => s.id)).toEqual(["s2", "s1", "s3"]);
  });

  it("moving to the last index is valid (last move)", () => {
    const t = moveSegment(track(), "s2", 2);
    expect(t.map((s) => s.id)).toEqual(["s1", "s3", "s2"]);
  });

  it("keeps scene grouping contiguous by rejecting a move that splits a scene", () => {
    const scened = resequence([
      seg("a", 2, "scene-1"),
      seg("b", 2, "scene-1"),
      seg("c", 2, "scene-2"),
    ]);
    // moving c between a and b would interleave scene-2 inside scene-1
    expect(() => moveSegment(scened, "c", 1)).toThrow();
  });

  it("allows a within-scene reorder", () => {
    const scened = resequence([
      seg("a", 2, "scene-1"),
      seg("b", 2, "scene-1"),
      seg("c", 2, "scene-2"),
    ]);
    const t = moveSegment(scened, "b", 0);
    expect(t.map((s) => s.id)).toEqual(["b", "a", "c"]);
  });

  it("rejects an out-of-range target index", () => {
    expect(() => moveSegment(track(), "s1", 5)).toThrow();
    expect(() => moveSegment(track(), "s1", -1)).toThrow();
  });

  it("throws for an unknown segment id", () => {
    expect(() => moveSegment(track(), "nope", 1)).toThrow();
  });

  it("is a no-op when moving to the same index", () => {
    const t = moveSegment(track(), "s2", 1);
    expect(t.map((s) => s.id)).toEqual(["s1", "s2", "s3"]);
  });
});

describe("move history (undo/redo)", () => {
  function history(): MoveHistory {
    return createMoveHistory(track());
  }

  it("applies a move and enables undo", () => {
    let h = history();
    h = applyMove(h, "s1", 2);
    expect(h.present.map((s) => s.id)).toEqual(["s2", "s3", "s1"]);
    expect(h.canUndo).toBe(true);
  });

  it("undo restores the original order and timing", () => {
    let h = history();
    h = applyMove(h, "s1", 2);
    h = undo(h);
    expect(h.present.map((s) => s.id)).toEqual(["s1", "s2", "s3"]);
    expect(h.present.map((s) => s.timelineStartSeconds)).toEqual([0, 2, 5]);
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the move", () => {
    let h = history();
    h = applyMove(h, "s1", 2);
    h = undo(h);
    h = redo(h);
    expect(h.present.map((s) => s.id)).toEqual(["s2", "s3", "s1"]);
  });

  it("rejects an invalid move without changing history", () => {
    const h = history();
    expect(() => applyMove(h, "s1", 9)).toThrow();
    expect(h.present.map((s) => s.id)).toEqual(["s1", "s2", "s3"]);
  });
});
