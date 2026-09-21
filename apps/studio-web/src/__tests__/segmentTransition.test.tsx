import { describe, it, expect } from "vitest";
import {
  SUPPORTED_TRANSITIONS,
  isSupportedTransition,
  setTransition,
  applyTransition,
  createTransitionHistory,
  undo,
  redo,
  type TransitionSegment,
  type TransitionHistory,
  type TransitionKind,
} from "../components/creator/segmentTransition";

function seg(over: Partial<TransitionSegment> = {}): TransitionSegment {
  return {
    id: "s1",
    sceneId: "scene-1",
    durationSeconds: 4,
    transition: null,
    transitionDurationSeconds: null,
    ...over,
  };
}

function track(): TransitionSegment[] {
  return [
    seg({ id: "s1", durationSeconds: 4 }),
    seg({ id: "s2", durationSeconds: 3 }),
    seg({ id: "s3", durationSeconds: 2 }),
  ];
}

describe("isSupportedTransition", () => {
  it("recognizes the renderer-supported transitions", () => {
    expect(SUPPORTED_TRANSITIONS).toEqual(["cut", "fade", "ken_burns", "ken_burns_lite"]);
    for (const t of SUPPORTED_TRANSITIONS) {
      expect(isSupportedTransition(t)).toBe(true);
    }
  });
  it("rejects unsupported values", () => {
    expect(isSupportedTransition("explode")).toBe(false);
    expect(isSupportedTransition("")).toBe(false);
  });
});

describe("setTransition", () => {
  it("sets a supported transition on a segment", () => {
    const next = setTransition(track(), "s2", "fade", 0.5);
    expect(next.find((s) => s.id === "s2")?.transition).toBe("fade");
    expect(next.find((s) => s.id === "s2")?.transitionDurationSeconds).toBe(0.5);
  });

  it("rejects an unsupported transition", () => {
    expect(() =>
      setTransition(track(), "s2", "explode" as unknown as TransitionKind, 0.5),
    ).toThrow();
  });

  it("cut ignores duration (boundary cut has no fade time)", () => {
    const next = setTransition(track(), "s2", "cut", 1);
    expect(next.find((s) => s.id === "s2")?.transition).toBe("cut");
    expect(next.find((s) => s.id === "s2")?.transitionDurationSeconds).toBeNull();
  });

  it("clears the transition when set to null", () => {
    const withFade = setTransition(track(), "s2", "fade", 0.5);
    const cleared = setTransition(withFade, "s2", null, null);
    expect(cleared.find((s) => s.id === "s2")?.transition).toBeNull();
    expect(cleared.find((s) => s.id === "s2")?.transitionDurationSeconds).toBeNull();
  });

  it("rejects a fade duration that exceeds the shorter neighboring segment", () => {
    // s3 duration is 2; a fade into s3 longer than 2 (or its previous neighbor) is invalid
    expect(() => setTransition(track(), "s3", "fade", 3)).toThrow();
  });

  it("allows a fade within the neighboring segment bounds", () => {
    const next = setTransition(track(), "s3", "fade", 1.5);
    expect(next.find((s) => s.id === "s3")?.transitionDurationSeconds).toBe(1.5);
  });

  it("rejects a non-positive fade duration", () => {
    expect(() => setTransition(track(), "s2", "fade", 0)).toThrow();
    expect(() => setTransition(track(), "s2", "fade", -1)).toThrow();
  });

  it("rejects a fade with no duration provided", () => {
    expect(() => setTransition(track(), "s2", "fade", null)).toThrow();
  });

  it("throws for an unknown segment id", () => {
    expect(() => setTransition(track(), "nope", "fade", 0.5)).toThrow();
  });
});

describe("transition history (undo/redo)", () => {
  function history(): TransitionHistory {
    return createTransitionHistory(track());
  }

  it("applies a transition and enables undo", () => {
    let h = history();
    h = applyTransition(h, "s2", "fade", 0.5);
    expect(h.present.find((s) => s.id === "s2")?.transition).toBe("fade");
    expect(h.canUndo).toBe(true);
  });

  it("undo restores the previous transition value", () => {
    let h = history();
    h = applyTransition(h, "s2", "fade", 0.5);
    h = undo(h);
    expect(h.present.find((s) => s.id === "s2")?.transition).toBeNull();
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the transition", () => {
    let h = history();
    h = applyTransition(h, "s2", "fade", 0.5);
    h = undo(h);
    h = redo(h);
    expect(h.present.find((s) => s.id === "s2")?.transition).toBe("fade");
  });

  it("rejects an invalid transition without changing history", () => {
    const h = history();
    expect(() =>
      applyTransition(h, "s2", "explode" as unknown as TransitionKind, 0.5),
    ).toThrow();
    expect(h.present.find((s) => s.id === "s2")?.transition).toBeNull();
  });
});
