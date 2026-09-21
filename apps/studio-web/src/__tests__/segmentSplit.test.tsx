import { describe, it, expect } from "vitest";
import {
  splitSegment,
  applySplit,
  createSplitHistory,
  undo,
  redo,
  type SplittableSegment,
  type SplitHistory,
} from "../components/creator/segmentSplit";

function seg(over: Partial<SplittableSegment> = {}): SplittableSegment {
  return {
    id: "seg-1",
    sceneId: "scene-1",
    kind: "image",
    source: "a.png",
    timelineStartSeconds: 0,
    durationSeconds: 6,
    trimStartSeconds: null,
    trimEndSeconds: null,
    ...over,
  };
}

describe("splitSegment", () => {
  it("splits an image segment into two at the playhead", () => {
    const [left, right] = splitSegment(seg(), 4);
    expect(left.durationSeconds).toBe(4);
    expect(right.durationSeconds).toBe(2);
    expect(right.timelineStartSeconds).toBe(4);
  });

  it("preserves total timing across the split", () => {
    const original = seg({ durationSeconds: 6 });
    const [left, right] = splitSegment(original, 2.5);
    expect(left.durationSeconds + right.durationSeconds).toBeCloseTo(6);
  });

  it("preserves scene association on both halves", () => {
    const [left, right] = splitSegment(seg({ sceneId: "scene-9" }), 3);
    expect(left.sceneId).toBe("scene-9");
    expect(right.sceneId).toBe("scene-9");
  });

  it("gives the two halves distinct stable ids derived from the original", () => {
    const [left, right] = splitSegment(seg({ id: "seg-1" }), 3);
    expect(left.id).not.toBe(right.id);
    expect(left.id).toContain("seg-1");
    expect(right.id).toContain("seg-1");
  });

  it("computes source offsets for video trims (right half starts later in source)", () => {
    const video = seg({
      kind: "video",
      source: "v.mp4",
      trimStartSeconds: 2,
      trimEndSeconds: 8,
      durationSeconds: 6,
    });
    const [left, right] = splitSegment(video, 4);
    // left keeps [2, 6), right continues [6, 8) in source time
    expect(left.trimStartSeconds).toBe(2);
    expect(left.trimEndSeconds).toBe(6);
    expect(right.trimStartSeconds).toBe(6);
    expect(right.trimEndSeconds).toBe(8);
  });

  it("leaves image trims null (no source offset)", () => {
    const [left, right] = splitSegment(seg(), 3);
    expect(left.trimStartSeconds).toBeNull();
    expect(right.trimStartSeconds).toBeNull();
  });

  it("rejects a split at the segment start (boundary, empty left)", () => {
    expect(() => splitSegment(seg(), 0)).toThrow();
  });

  it("rejects a split at the segment end (boundary, empty right)", () => {
    expect(() => splitSegment(seg({ durationSeconds: 6 }), 6)).toThrow();
  });

  it("rejects a split outside the segment window", () => {
    expect(() => splitSegment(seg({ timelineStartSeconds: 2, durationSeconds: 4 }), 1)).toThrow();
    expect(() => splitSegment(seg({ timelineStartSeconds: 2, durationSeconds: 4 }), 7)).toThrow();
  });
});

describe("split history (undo/redo)", () => {
  function history(): SplitHistory {
    return createSplitHistory([seg({ id: "s1", durationSeconds: 6 })]);
  }

  it("applies a split atomically, replacing one segment with two", () => {
    let h = history();
    h = applySplit(h, "s1", 4);
    expect(h.present).toHaveLength(2);
    expect(h.canUndo).toBe(true);
  });

  it("undoes back to the single original segment", () => {
    let h = history();
    h = applySplit(h, "s1", 4);
    h = undo(h);
    expect(h.present).toHaveLength(1);
    expect(h.present[0].id).toBe("s1");
    expect(h.canRedo).toBe(true);
  });

  it("redoes the undone split", () => {
    let h = history();
    h = applySplit(h, "s1", 4);
    h = undo(h);
    h = redo(h);
    expect(h.present).toHaveLength(2);
  });

  it("rejects an out-of-bounds split without changing history", () => {
    const h = history();
    expect(() => applySplit(h, "s1", 0)).toThrow();
    expect(h.present).toHaveLength(1);
  });

  it("throws for an unknown segment id", () => {
    const h = history();
    expect(() => applySplit(h, "nope", 3)).toThrow();
  });
});
