import { describe, it, expect } from "vitest";
import {
  replaceAsset,
  applyReplace,
  createReplaceHistory,
  undo,
  redo,
  IncompatibleAssetError,
  InaccessibleAssetError,
  type ReplaceableSegment,
  type ReplacementAsset,
  type ReplaceHistory,
} from "../components/creator/segmentReplace";

function seg(over: Partial<ReplaceableSegment> = {}): ReplaceableSegment {
  return {
    id: "seg-1",
    sceneId: "scene-1",
    kind: "video",
    assetId: 10,
    source: "old.mp4",
    durationSeconds: 4,
    trimStartSeconds: 1,
    trimEndSeconds: 5,
    ...over,
  };
}

function asset(over: Partial<ReplacementAsset> = {}): ReplacementAsset {
  return {
    id: 20,
    workspaceId: 1,
    kind: "video",
    source: "new.mp4",
    durationSeconds: 30,
    ...over,
  };
}

const WORKSPACE = 1;

describe("replaceAsset", () => {
  it("swaps the asset reference and source, keeping scene/id", () => {
    const next = replaceAsset(seg(), asset(), WORKSPACE);
    expect(next.id).toBe("seg-1");
    expect(next.sceneId).toBe("scene-1");
    expect(next.assetId).toBe(20);
    expect(next.source).toBe("new.mp4");
  });

  it("rejects an incompatible media kind", () => {
    expect(() => replaceAsset(seg({ kind: "video" }), asset({ kind: "image" }), WORKSPACE)).toThrow(
      IncompatibleAssetError,
    );
  });

  it("rejects an inaccessible (cross-workspace) asset", () => {
    expect(() => replaceAsset(seg(), asset({ workspaceId: 2 }), WORKSPACE)).toThrow(
      InaccessibleAssetError,
    );
  });

  it("preserves existing trims when the new source is long enough", () => {
    const next = replaceAsset(seg({ trimStartSeconds: 1, trimEndSeconds: 5 }), asset({ durationSeconds: 30 }), WORKSPACE);
    expect(next.trimStartSeconds).toBe(1);
    expect(next.trimEndSeconds).toBe(5);
  });

  it("clamps trims when the new source is shorter than the existing trim window", () => {
    const next = replaceAsset(
      seg({ trimStartSeconds: 1, trimEndSeconds: 5 }),
      asset({ durationSeconds: 3 }),
      WORKSPACE,
    );
    // trim end clamped to new source duration; start clamped below end
    expect(next.trimEndSeconds).toBe(3);
    expect(next.trimStartSeconds).toBe(1);
  });

  it("clamps trim start too when new source is shorter than the start", () => {
    const next = replaceAsset(
      seg({ kind: "video", trimStartSeconds: 4, trimEndSeconds: 6, durationSeconds: 2 }),
      asset({ durationSeconds: 2 }),
      WORKSPACE,
    );
    expect(next.trimEndSeconds).toBe(2);
    expect(next.trimStartSeconds).not.toBeNull();
    expect(next.trimStartSeconds ?? 0).toBeLessThan(2);
  });

  it("resets trims to null when replacing with an image (no source duration)", () => {
    const next = replaceAsset(
      seg({ kind: "image" }),
      asset({ kind: "image", durationSeconds: null }),
      WORKSPACE,
    );
    expect(next.trimStartSeconds).toBeNull();
    expect(next.trimEndSeconds).toBeNull();
  });

  it("recomputes the effective duration to fit the new source when trims shrink", () => {
    const next = replaceAsset(
      seg({ trimStartSeconds: 0, trimEndSeconds: 5, durationSeconds: 5 }),
      asset({ durationSeconds: 3 }),
      WORKSPACE,
    );
    expect(next.durationSeconds).toBe(3);
  });
});

describe("replace history (undo/redo)", () => {
  function history(): ReplaceHistory {
    return createReplaceHistory([seg({ id: "s1", assetId: 10 })], WORKSPACE);
  }

  it("applies a replacement and enables undo", () => {
    let h = history();
    h = applyReplace(h, "s1", asset({ id: 20 }));
    expect(h.present[0].assetId).toBe(20);
    expect(h.canUndo).toBe(true);
  });

  it("undo restores the original asset and trims", () => {
    let h = history();
    h = applyReplace(h, "s1", asset({ id: 20 }));
    h = undo(h);
    expect(h.present[0].assetId).toBe(10);
    expect(h.present[0].source).toBe("old.mp4");
    expect(h.canRedo).toBe(true);
  });

  it("redo re-applies the replacement", () => {
    let h = history();
    h = applyReplace(h, "s1", asset({ id: 20 }));
    h = undo(h);
    h = redo(h);
    expect(h.present[0].assetId).toBe(20);
  });

  it("rejects an incompatible replacement without changing history", () => {
    const h = history();
    expect(() => applyReplace(h, "s1", asset({ id: 20, kind: "image" }))).toThrow(
      IncompatibleAssetError,
    );
    expect(h.present[0].assetId).toBe(10);
  });

  it("throws for an unknown segment id", () => {
    const h = history();
    expect(() => applyReplace(h, "nope", asset())).toThrow();
  });
});
