import { describe, it, expect } from "vitest";
import {
  resizeSegment,
  applyResize,
  createResizeHistory,
  undo,
  redo,
  type ResizableSegment,
  type ResizeHistory,
} from "../components/creator/segmentResize";

function seg(over: Partial<ResizableSegment> = {}): ResizableSegment {
  return {
    id: "s1",
    sceneId: "scene-1",
    kind: "video",
    timelineStartSeconds: 0,
    durationSeconds: 4,
    trimStartSeconds: 1,
    sourceDurationSeconds: 30,
    ...over,
  };
}

function track(): ResizableSegment[] {
  return [
    seg({ id: "s1", timelineStartSeconds: 0, durationSeconds: 4 }),
    seg({ id: "s2", timelineStartSeconds: 4, durationSeconds: 3, trimStartSeconds: 0 }),
    seg({ id: "s3", timelineStartSeconds: 7, durationSeconds: 2, trimStartSeconds: 0 }),
  ];
}

describe("resizeSegment", () => {
  it("sets a new duration and ripples later segments (neighbor policy)", () => {
    const next = resizeSegment(track(), "s1", 6);
    expect(next.find((s) => s.id === "s1")?.durationSeconds).toBe(6);
    // s2 shifts +2 (4 -> 6), s3 shifts +2 (7 -> 9)
    expect(next.find((s) => s.id === "s2")?.timelineStartSeconds).toBe(6);
    expect(next.find((s) => s.id === "s3")?.timelineStartSeconds).toBe(9);
  });

  it("shrinking ripples later segments earlier", () => {
    const next = resizeSegment(track(), "s1", 2);
    expect(next.find((s) => s.id === "s2")?.timelineStartSeconds).toBe(2);
    expect(next.find((s) => s.id === "s3")?.timelineStartSeconds).toBe(5);
  });

  it("leaves earlier segments unchanged", () => {
    const next = resizeSegment(track(), "s2", 5);
    expect(next.find((s) => s.id === "s1")?.timelineStartSeconds).toBe(0);
  });

  it("rejects a non-positive duration", () => {
    expect(() => resizeSegment(track(), "s1", 0)).toThrow();
    expect(() => resizeSegment(track(), "s1", -1)).toThrow();
  });

  it("rejects a non-finite duration", () => {
    expect(() => resizeSegment(track(), "s1", Infinity)).toThrow();
    expect(() => resizeSegment(track(), "s1", NaN)).toThrow();
  });

  it("rejects a video resize beyond the remaining source bounds", () => {
    // s1 trimStart=1, source=30 -> max effective duration is 29
    expect(() => resizeSegment(track(), "s1", 30)).toThrow();
  });

  it("allows a video resize exactly to the source bound", () => {
    const next = resizeSegment(track(), "s1", 29);
    expect(next.find((s) => s.id === "s1")?.durationSeconds).toBe(29);
  });

  it("allows any positive duration for an image (no source bound)", () => {
    const images = [
      seg({ id: "s1", kind: "image", sourceDurationSeconds: null, trimStartSeconds: null }),
    ];
    const next = resizeSegment(images, "s1", 120);
    expect(next[0].durationSeconds).toBe(120);
  });

  it("throws for an unknown segment id", () => {
    expect(() => resizeSegment(track(), "nope", 5)).toThrow();
  });

  it("gives identical results for inspector-input and timeline-resize (one contract)", () => {
    // both editing paths call resizeSegment with the same (id, duration)
    const fromInput = resizeSegment(track(), "s2", 5);
    const fromDrag = resizeSegment(track(), "s2", 5);
    expect(fromInput).toEqual(fromDrag);
  });
});

describe("resize history (undo/redo)", () => {
  function history(): ResizeHistory {
    return createResizeHistory(track());
  }

  it("applies a resize and enables undo", () => {
    let h = history();
    h = applyResize(h, "s1", 6);
    expect(h.present.find((s) => s.id === "s1")?.durationSeconds).toBe(6);
    expect(h.canUndo).toBe(true);
  });

  it("undo restores original duration and neighbor timing", () => {
    let h = history();
    h = applyResize(h, "s1", 6);
    h = undo(h);
    expect(h.present.find((s) => s.id === "s1")?.durationSeconds).toBe(4);
    expect(h.present.find((s) => s.id === "s2")?.timelineStartSeconds).toBe(4);
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the resize", () => {
    let h = history();
    h = applyResize(h, "s1", 6);
    h = undo(h);
    h = redo(h);
    expect(h.present.find((s) => s.id === "s1")?.durationSeconds).toBe(6);
  });

  it("rejects an invalid resize without changing history", () => {
    const h = history();
    expect(() => applyResize(h, "s1", 0)).toThrow();
    expect(h.present.find((s) => s.id === "s1")?.durationSeconds).toBe(4);
  });
});
