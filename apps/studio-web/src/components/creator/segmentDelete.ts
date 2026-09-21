/**
 * segmentDelete — pure model for deleting a timeline segment under a defined
 * gap/ripple policy, with undo/redo.
 *
 * deleteSegment removes one segment from an ordered track. Under the "gap"
 * policy the remaining segments keep their timeline positions (a gap is left);
 * under "ripple" every segment after the deleted one shifts earlier by the
 * deleted duration so no gap remains. Only the segment reference is removed —
 * the underlying MediaAsset is never touched, so other segments sharing the same
 * assetId are unaffected, as are segments in other scenes. Deleting the last
 * segment yields an empty track. applyDelete performs the removal atomically
 * over a DeleteHistory so undo restores the deleted segment at its original
 * position (one undoable step).
 */

export interface DeletableSegment {
  id: string;
  sceneId: string;
  assetId: number;
  timelineStartSeconds: number;
  durationSeconds: number;
}

export type DeletePolicy = "gap" | "ripple";

export interface DeleteHistory {
  policy: DeletePolicy;
  past: DeletableSegment[][];
  present: DeletableSegment[];
  future: DeletableSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * Remove ``segmentId`` from an ordered track. "gap" preserves positions;
 * "ripple" shifts later segments earlier by the deleted duration. Throws when
 * the id is not present. The underlying MediaAsset is not deleted.
 */
export function deleteSegment(
  segments: DeletableSegment[],
  segmentId: string,
  policy: DeletePolicy,
): DeletableSegment[] {
  const index = segments.findIndex((s) => s.id === segmentId);
  if (index === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }
  const deleted = segments[index];
  const remaining = segments.filter((s) => s.id !== segmentId);
  if (policy === "gap") {
    return remaining;
  }
  return remaining.map((s) =>
    s.timelineStartSeconds >= deleted.timelineStartSeconds
      ? { ...s, timelineStartSeconds: s.timelineStartSeconds - deleted.durationSeconds }
      : s,
  );
}

export function createDeleteHistory(
  segments: DeletableSegment[],
  policy: DeletePolicy,
): DeleteHistory {
  return {
    policy,
    past: [],
    present: segments,
    future: [],
    canUndo: false,
    canRedo: false,
  };
}

export function applyDelete(history: DeleteHistory, segmentId: string): DeleteHistory {
  const present = deleteSegment(history.present, segmentId, history.policy);
  return {
    ...history,
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: DeleteHistory): DeleteHistory {
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

export function redo(history: DeleteHistory): DeleteHistory {
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
