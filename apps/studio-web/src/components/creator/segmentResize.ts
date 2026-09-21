/**
 * segmentResize — pure model for editing a segment's duration through one
 * command contract (Scene Inspector input or timeline resize), with an explicit
 * neighbor timing policy and undo/redo.
 *
 * resizeSegment sets a new duration and ripples every later segment by the delta
 * so the track stays contiguous (neighbor policy); earlier segments are
 * unchanged. The duration must be positive and finite, and for a video source it
 * cannot exceed the remaining source (sourceDuration - trimStart); images have no
 * source bound. Because both the inspector and the drag-resize call this same
 * function with (id, duration), UI input and timeline resize produce identical
 * results. applyResize performs the edit atomically over a ResizeHistory so undo
 * restores the original duration and neighbor timing.
 */

export type ResizeKind = "image" | "video" | "audio";

export interface ResizableSegment {
  id: string;
  sceneId: string;
  kind: ResizeKind;
  timelineStartSeconds: number;
  durationSeconds: number;
  trimStartSeconds: number | null;
  sourceDurationSeconds: number | null;
}

export interface ResizeHistory {
  past: ResizableSegment[][];
  present: ResizableSegment[];
  future: ResizableSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * Set ``segmentId``'s duration and ripple later segments. Throws on an unknown
 * id, a non-positive or non-finite duration, or (for video) a duration beyond
 * the remaining source (sourceDuration - trimStart).
 */
export function resizeSegment(
  segments: ResizableSegment[],
  segmentId: string,
  durationSeconds: number,
): ResizableSegment[] {
  const index = segments.findIndex((s) => s.id === segmentId);
  if (index === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw new RangeError("duration must be positive and finite");
  }

  const target = segments[index];
  if (target.sourceDurationSeconds !== null) {
    const available = target.sourceDurationSeconds - (target.trimStartSeconds ?? 0);
    if (durationSeconds > available + 1e-9) {
      throw new RangeError(
        `duration ${durationSeconds} exceeds remaining source ${available}`,
      );
    }
  }

  const delta = durationSeconds - target.durationSeconds;
  return segments.map((s, i) => {
    if (i === index) {
      return { ...s, durationSeconds };
    }
    if (i > index) {
      return { ...s, timelineStartSeconds: s.timelineStartSeconds + delta };
    }
    return s;
  });
}

export function createResizeHistory(segments: ResizableSegment[]): ResizeHistory {
  return { past: [], present: segments, future: [], canUndo: false, canRedo: false };
}

export function applyResize(
  history: ResizeHistory,
  segmentId: string,
  durationSeconds: number,
): ResizeHistory {
  const present = resizeSegment(history.present, segmentId, durationSeconds);
  return {
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: ResizeHistory): ResizeHistory {
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

export function redo(history: ResizeHistory): ResizeHistory {
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
