/**
 * segmentMove — pure model for moving/reordering timeline segments with stable
 * ids, a documented timing policy, and undo/redo.
 *
 * Timing policy: after any reorder the track is re-sequenced (resequence) so
 * segments are contiguous with no gaps or overlaps — each segment's
 * timelineStartSeconds is the sum of preceding durations, in the new order.
 * Segment ids are stable across moves. Scene grouping is kept contiguous: a move
 * that would interleave one scene's segments inside another is rejected, so the
 * saved Timeline order, Preview, and scene grouping stay consistent. moveSegment
 * validates the target index and id; applyMove performs the move atomically over
 * a MoveHistory so undo restores the original order and timing.
 */

export interface OrderedSegment {
  id: string;
  sceneId: string;
  durationSeconds: number;
  timelineStartSeconds: number;
}

export interface MoveHistory {
  past: OrderedSegment[][];
  present: OrderedSegment[];
  future: OrderedSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

/** Recompute contiguous timeline positions from the current order (no gaps). */
export function resequence(segments: OrderedSegment[]): OrderedSegment[] {
  let cursor = 0;
  return segments.map((s) => {
    const placed = { ...s, timelineStartSeconds: cursor };
    cursor += s.durationSeconds;
    return placed;
  });
}

/** True when each scene's segments form one contiguous run in the order. */
function sceneGroupingContiguous(segments: OrderedSegment[]): boolean {
  const seen = new Set<string>();
  let previous: string | null = null;
  for (const s of segments) {
    if (s.sceneId !== previous) {
      if (seen.has(s.sceneId)) {
        return false;
      }
      seen.add(s.sceneId);
      previous = s.sceneId;
    }
  }
  return true;
}

/**
 * Move ``segmentId`` to ``targetIndex`` and re-sequence. Throws on an unknown id,
 * an out-of-range index, or a move that would break scene-grouping contiguity.
 */
export function moveSegment(
  segments: OrderedSegment[],
  segmentId: string,
  targetIndex: number,
): OrderedSegment[] {
  const from = segments.findIndex((s) => s.id === segmentId);
  if (from === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }
  if (targetIndex < 0 || targetIndex >= segments.length) {
    throw new RangeError(`target index ${targetIndex} out of range`);
  }
  if (targetIndex === from) {
    return resequence(segments);
  }

  const without = [...segments.slice(0, from), ...segments.slice(from + 1)];
  const reordered = [
    ...without.slice(0, targetIndex),
    segments[from],
    ...without.slice(targetIndex),
  ];
  if (!sceneGroupingContiguous(reordered)) {
    throw new Error("move would break scene grouping contiguity");
  }
  return resequence(reordered);
}

export function createMoveHistory(segments: OrderedSegment[]): MoveHistory {
  return {
    past: [],
    present: resequence(segments),
    future: [],
    canUndo: false,
    canRedo: false,
  };
}

export function applyMove(
  history: MoveHistory,
  segmentId: string,
  targetIndex: number,
): MoveHistory {
  const present = moveSegment(history.present, segmentId, targetIndex);
  return {
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: MoveHistory): MoveHistory {
  if (history.past.length === 0) {
    return history;
  }
  const previous = history.past[history.past.length - 1];
  const past = history.past.slice(0, -1);
  return {
    past,
    present: previous,
    future: [history.present, ...history.future],
    canUndo: past.length > 0,
    canRedo: true,
  };
}

export function redo(history: MoveHistory): MoveHistory {
  if (history.future.length === 0) {
    return history;
  }
  const next = history.future[0];
  const future = history.future.slice(1);
  return {
    past: [...history.past, history.present],
    present: next,
    future,
    canUndo: true,
    canRedo: future.length > 0,
  };
}
