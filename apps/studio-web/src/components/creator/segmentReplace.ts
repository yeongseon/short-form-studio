/**
 * segmentReplace — pure model for replacing a segment's asset with an
 * authorized, compatible MediaAsset, with defined trim/duration behavior and
 * undo/redo.
 *
 * replaceAsset swaps a segment's asset reference and source while keeping its id
 * and scene association. The replacement must be the same media kind
 * (IncompatibleAssetError otherwise) and belong to the caller's workspace
 * (InaccessibleAssetError otherwise — the cross-workspace/404 guard). When the
 * new source is shorter than the existing trim window, trims are clamped to the
 * new source duration (end first, then start below end) and the effective
 * duration recomputed so it always fits the new source. Replacing with an image
 * (no source duration) resets trims to null. applyReplace performs the swap
 * atomically over a ReplaceHistory so undo restores the original asset/trims.
 */

export type ReplaceKind = "image" | "video" | "audio";

export interface ReplaceableSegment {
  id: string;
  sceneId: string;
  kind: ReplaceKind;
  assetId: number;
  source: string;
  durationSeconds: number;
  trimStartSeconds: number | null;
  trimEndSeconds: number | null;
}

export interface ReplacementAsset {
  id: number;
  workspaceId: number;
  kind: ReplaceKind;
  source: string;
  durationSeconds: number | null;
}

export interface ReplaceHistory {
  workspaceId: number;
  past: ReplaceableSegment[][];
  present: ReplaceableSegment[];
  future: ReplaceableSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

export class IncompatibleAssetError extends Error {
  constructor(segmentKind: ReplaceKind, assetKind: ReplaceKind) {
    super(`cannot replace a ${segmentKind} segment with a ${assetKind} asset`);
    this.name = "IncompatibleAssetError";
  }
}

export class InaccessibleAssetError extends Error {
  constructor(assetId: number) {
    super(`asset ${assetId} is not accessible in this workspace`);
    this.name = "InaccessibleAssetError";
  }
}

/**
 * Replace ``segment``'s asset with ``asset`` for ``workspaceId``. Throws when
 * the kinds differ or the asset is outside the workspace. Clamps trims to the
 * new source duration when it is shorter than the existing window.
 */
export function replaceAsset(
  segment: ReplaceableSegment,
  asset: ReplacementAsset,
  workspaceId: number,
): ReplaceableSegment {
  if (asset.kind !== segment.kind) {
    throw new IncompatibleAssetError(segment.kind, asset.kind);
  }
  if (asset.workspaceId !== workspaceId) {
    throw new InaccessibleAssetError(asset.id);
  }

  const base: ReplaceableSegment = {
    ...segment,
    assetId: asset.id,
    source: asset.source,
  };

  if (asset.durationSeconds === null) {
    return {
      ...base,
      trimStartSeconds: null,
      trimEndSeconds: null,
    };
  }

  if (segment.trimStartSeconds === null || segment.trimEndSeconds === null) {
    return base;
  }

  const trimEnd = Math.min(segment.trimEndSeconds, asset.durationSeconds);
  const trimStart = Math.min(segment.trimStartSeconds, Math.max(0, trimEnd - 1e-3));
  return {
    ...base,
    trimStartSeconds: trimStart,
    trimEndSeconds: trimEnd,
    durationSeconds: trimEnd - trimStart,
  };
}

export function createReplaceHistory(
  segments: ReplaceableSegment[],
  workspaceId: number,
): ReplaceHistory {
  return {
    workspaceId,
    past: [],
    present: segments,
    future: [],
    canUndo: false,
    canRedo: false,
  };
}

export function applyReplace(
  history: ReplaceHistory,
  segmentId: string,
  asset: ReplacementAsset,
): ReplaceHistory {
  const index = history.present.findIndex((s) => s.id === segmentId);
  if (index === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }
  const replaced = replaceAsset(history.present[index], asset, history.workspaceId);
  const present = [
    ...history.present.slice(0, index),
    replaced,
    ...history.present.slice(index + 1),
  ];
  return {
    ...history,
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: ReplaceHistory): ReplaceHistory {
  if (history.past.length === 0) {
    return history;
  }
  const previous = history.past[history.past.length - 1];
  const past = history.past.slice(0, -1);
  return {
    ...history,
    past,
    present: previous,
    future: [history.present, ...history.future],
    canUndo: past.length > 0,
    canRedo: true,
  };
}

export function redo(history: ReplaceHistory): ReplaceHistory {
  if (history.future.length === 0) {
    return history;
  }
  const next = history.future[0];
  const future = history.future.slice(1);
  return {
    ...history,
    past: [...history.past, history.present],
    present: next,
    future,
    canUndo: true,
    canRedo: future.length > 0,
  };
}
