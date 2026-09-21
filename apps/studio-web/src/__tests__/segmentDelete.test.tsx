import { describe, it, expect } from "vitest";
import {
  deleteSegment,
  applyDelete,
  createDeleteHistory,
  undo,
  redo,
  type DeletableSegment,
  type DeletePolicy,
  type DeleteHistory,
} from "../components/creator/segmentDelete";

function seg(over: Partial<DeletableSegment> = {}): DeletableSegment {
  return {
    id: "seg-1",
    sceneId: "scene-1",
    assetId: 10,
    timelineStartSeconds: 0,
    durationSeconds: 4,
    ...over,
  };
}

function track(): DeletableSegment[] {
  return [
    seg({ id: "s1", assetId: 10, timelineStartSeconds: 0, durationSeconds: 4 }),
    seg({ id: "s2", assetId: 11, timelineStartSeconds: 4, durationSeconds: 3 }),
    seg({ id: "s3", assetId: 12, timelineStartSeconds: 7, durationSeconds: 2 }),
  ];
}

describe("deleteSegment", () => {
  it("removes the segment and leaves a gap under the 'gap' policy", () => {
    const next = deleteSegment(track(), "s2", "gap");
    expect(next.map((s) => s.id)).toEqual(["s1", "s3"]);
    // s3 stays where it was (gap left at 4..7)
    expect(next.find((s) => s.id === "s3")?.timelineStartSeconds).toBe(7);
  });

  it("ripples later segments earlier under the 'ripple' policy", () => {
    const next = deleteSegment(track(), "s2", "ripple");
    expect(next.map((s) => s.id)).toEqual(["s1", "s3"]);
    // s3 shifts left by the deleted duration (3s): 7 -> 4
    expect(next.find((s) => s.id === "s3")?.timelineStartSeconds).toBe(4);
  });

  it("keeps segments before the deleted one unchanged under ripple", () => {
    const next = deleteSegment(track(), "s2", "ripple");
    expect(next.find((s) => s.id === "s1")?.timelineStartSeconds).toBe(0);
  });

  it("does not delete the underlying MediaAsset (only the segment reference)", () => {
    // s1 and another segment share assetId 10; deleting s1 must not affect others
    const shared = [
      seg({ id: "s1", assetId: 10, timelineStartSeconds: 0, durationSeconds: 4 }),
      seg({ id: "s2", assetId: 10, timelineStartSeconds: 4, durationSeconds: 4 }),
    ];
    const next = deleteSegment(shared, "s1", "gap");
    expect(next.map((s) => s.id)).toEqual(["s2"]);
    expect(next[0].assetId).toBe(10);
  });

  it("leaves other scenes' segments untouched", () => {
    const multiScene = [
      seg({ id: "a", sceneId: "scene-1", timelineStartSeconds: 0, durationSeconds: 4 }),
      seg({ id: "b", sceneId: "scene-2", timelineStartSeconds: 4, durationSeconds: 4 }),
    ];
    const next = deleteSegment(multiScene, "a", "gap");
    expect(next.map((s) => s.id)).toEqual(["b"]);
    expect(next[0].sceneId).toBe("scene-2");
  });

  it("returns an empty track when the last segment is deleted", () => {
    const single = [seg({ id: "only" })];
    expect(deleteSegment(single, "only", "gap")).toEqual([]);
  });

  it("throws for an unknown segment id", () => {
    expect(() => deleteSegment(track(), "nope", "gap")).toThrow();
  });
});

describe("delete history (undo/redo)", () => {
  function history(policy: DeletePolicy = "ripple"): DeleteHistory {
    return createDeleteHistory(track(), policy);
  }

  it("applies a delete and enables undo", () => {
    let h = history();
    h = applyDelete(h, "s2");
    expect(h.present.map((s) => s.id)).toEqual(["s1", "s3"]);
    expect(h.canUndo).toBe(true);
  });

  it("undo restores the deleted segment at its original position", () => {
    let h = history();
    h = applyDelete(h, "s2");
    h = undo(h);
    expect(h.present.map((s) => s.id)).toEqual(["s1", "s2", "s3"]);
    expect(h.present.find((s) => s.id === "s3")?.timelineStartSeconds).toBe(7);
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the delete", () => {
    let h = history();
    h = applyDelete(h, "s2");
    h = undo(h);
    h = redo(h);
    expect(h.present.map((s) => s.id)).toEqual(["s1", "s3"]);
  });

  it("keeps selection valid: deleted id is no longer present", () => {
    let h = history();
    h = applyDelete(h, "s2");
    expect(h.present.some((s) => s.id === "s2")).toBe(false);
  });

  it("throws on unknown id without changing history", () => {
    const h = history();
    expect(() => applyDelete(h, "nope")).toThrow();
    expect(h.present).toHaveLength(3);
  });
});
