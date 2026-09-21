import { describe, it, expect } from "vitest";
import {
  OUTPUT_PRESETS,
  outputPreset,
  fitModeFor,
  switchOutput,
  applyOutputSwitch,
  createOutputHistory,
  undo,
  redo,
  type OutputProject,
  type OutputHistory,
} from "../components/creator/outputSwitch";

function project(over: Partial<OutputProject> = {}): OutputProject {
  return {
    output: outputPreset("short_vertical"),
    encoding: { name: "high_quality", crf: 18, preset: "slow" },
    segments: [
      { id: "s1", assetId: 10, durationSeconds: 4, fitMode: "cover" },
      { id: "s2", assetId: 11, durationSeconds: 3, fitMode: "contain" },
    ],
    ...over,
  };
}

describe("outputPreset", () => {
  it("resolves the three short presets with correct dimensions", () => {
    expect(outputPreset("short_vertical")).toEqual({ width: 1080, height: 1920, fps: 30, preset: "short_vertical" });
    expect(outputPreset("short_square")).toEqual({ width: 1080, height: 1080, fps: 30, preset: "short_square" });
    expect(outputPreset("short_landscape")).toEqual({ width: 1920, height: 1080, fps: 30, preset: "short_landscape" });
  });
  it("throws for an unknown preset", () => {
    expect(() => outputPreset("cinemascope")).toThrow();
  });
  it("exposes the supported preset names", () => {
    expect(OUTPUT_PRESETS).toEqual(["short_vertical", "short_square", "short_landscape"]);
  });
});

describe("fitModeFor", () => {
  it("keeps cover when aspect is unchanged", () => {
    expect(fitModeFor("cover", "short_vertical", "short_vertical")).toBe("cover");
  });
  it("switches cover to contain when moving to a different aspect (avoid cropping edits)", () => {
    expect(fitModeFor("cover", "short_vertical", "short_landscape")).toBe("contain");
  });
  it("leaves an explicit contain as contain", () => {
    expect(fitModeFor("contain", "short_vertical", "short_square")).toBe("contain");
  });
});

describe("switchOutput", () => {
  it("switches to a new aspect and updates only the output dimensions", () => {
    const next = switchOutput(project(), "short_landscape");
    expect(next.output).toEqual(outputPreset("short_landscape"));
  });

  it("preserves timeline edits (segments, durations, asset ids)", () => {
    const p = project();
    const next = switchOutput(p, "short_square");
    expect(next.segments.map((s) => s.id)).toEqual(["s1", "s2"]);
    expect(next.segments.map((s) => s.durationSeconds)).toEqual([4, 3]);
    expect(next.segments.map((s) => s.assetId)).toEqual([10, 11]);
  });

  it("preserves encoding quality", () => {
    const next = switchOutput(project(), "short_landscape");
    expect(next.encoding).toEqual({ name: "high_quality", crf: 18, preset: "slow" });
  });

  it("applies explicit fitting rules across an aspect change", () => {
    const next = switchOutput(project(), "short_landscape");
    // s1 was cover on a different aspect -> contain to avoid cropping
    expect(next.segments.find((s) => s.id === "s1")?.fitMode).toBe("contain");
    // s2 was explicitly contain -> stays contain
    expect(next.segments.find((s) => s.id === "s2")?.fitMode).toBe("contain");
  });

  it("is a no-op fit change when switching to the same aspect", () => {
    const p = project();
    const next = switchOutput(p, "short_vertical");
    expect(next.segments.find((s) => s.id === "s1")?.fitMode).toBe("cover");
  });

  it("rejects an unknown preset", () => {
    expect(() => switchOutput(project(), "imax")).toThrow();
  });
});

describe("output history (undo/redo, reversible)", () => {
  function history(): OutputHistory {
    return createOutputHistory(project());
  }

  it("applies a switch and enables undo", () => {
    let h = history();
    h = applyOutputSwitch(h, "short_landscape");
    expect(h.present.output.width).toBe(1920);
    expect(h.canUndo).toBe(true);
  });

  it("undo reverses the output change without losing edits", () => {
    let h = history();
    h = applyOutputSwitch(h, "short_landscape");
    h = undo(h);
    expect(h.present.output).toEqual(outputPreset("short_vertical"));
    expect(h.present.segments.map((s) => s.id)).toEqual(["s1", "s2"]);
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the switch", () => {
    let h = history();
    h = applyOutputSwitch(h, "short_landscape");
    h = undo(h);
    h = redo(h);
    expect(h.present.output.width).toBe(1920);
  });

  it("rejects an invalid switch without changing history", () => {
    const h = history();
    expect(() => applyOutputSwitch(h, "imax")).toThrow();
    expect(h.present.output).toEqual(outputPreset("short_vertical"));
  });
});
