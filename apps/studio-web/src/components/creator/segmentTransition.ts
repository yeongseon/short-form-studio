/**
 * segmentTransition — pure model for editing a segment's scene transition
 * through shared commands, validated against renderer support and neighboring
 * segment durations, with undo/redo.
 *
 * Only the renderer-supported transitions are accepted (SUPPORTED_TRANSITIONS,
 * matching the compiler's allowlist). A "cut" is an instantaneous boundary with
 * no fade time, so its duration is always null. A timed transition ("fade" and
 * the ken_burns variants) requires a positive duration that does not exceed the
 * shorter of the segment and its previous neighbor, so the overlap always fits
 * both clips (preview/render parity). setTransition returns the updated track;
 * applyTransition performs the edit atomically over a TransitionHistory so undo
 * restores the previous transition value.
 */

export const SUPPORTED_TRANSITIONS = [
  "cut",
  "fade",
  "ken_burns",
  "ken_burns_lite",
] as const;

export type TransitionKind = (typeof SUPPORTED_TRANSITIONS)[number];

const _TIMED_TRANSITIONS: ReadonlySet<TransitionKind> = new Set<TransitionKind>([
  "fade",
  "ken_burns",
  "ken_burns_lite",
]);

export interface TransitionSegment {
  id: string;
  sceneId: string;
  durationSeconds: number;
  transition: string | null;
  transitionDurationSeconds: number | null;
}

export interface TransitionHistory {
  past: TransitionSegment[][];
  present: TransitionSegment[];
  future: TransitionSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

/** True when ``value`` is a renderer-supported transition. */
export function isSupportedTransition(value: string): value is TransitionKind {
  return (SUPPORTED_TRANSITIONS as readonly string[]).includes(value);
}

/**
 * Set (or clear, when ``transition`` is null) a segment's transition. Throws on
 * an unknown id, an unsupported transition, or a timed transition whose duration
 * is missing, non-positive, or longer than the shorter of the segment and its
 * previous neighbor.
 */
export function setTransition(
  segments: TransitionSegment[],
  segmentId: string,
  transition: TransitionKind | null,
  durationSeconds: number | null,
): TransitionSegment[] {
  const index = segments.findIndex((s) => s.id === segmentId);
  if (index === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }

  if (transition === null) {
    return segments.map((s, i) =>
      i === index ? { ...s, transition: null, transitionDurationSeconds: null } : s,
    );
  }

  if (!isSupportedTransition(transition)) {
    throw new Error(`unsupported transition: ${transition}`);
  }

  if (!_TIMED_TRANSITIONS.has(transition)) {
    return segments.map((s, i) =>
      i === index ? { ...s, transition, transitionDurationSeconds: null } : s,
    );
  }

  if (durationSeconds === null || !Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw new RangeError("timed transition requires a positive duration");
  }

  const segment = segments[index];
  const previous = index > 0 ? segments[index - 1] : null;
  const bound = Math.min(
    segment.durationSeconds,
    previous?.durationSeconds ?? segment.durationSeconds,
  );
  if (durationSeconds > bound + 1e-9) {
    throw new RangeError(
      `transition duration ${durationSeconds} exceeds neighbor bound ${bound}`,
    );
  }

  return segments.map((s, i) =>
    i === index ? { ...s, transition, transitionDurationSeconds: durationSeconds } : s,
  );
}

export function createTransitionHistory(
  segments: TransitionSegment[],
): TransitionHistory {
  return { past: [], present: segments, future: [], canUndo: false, canRedo: false };
}

export function applyTransition(
  history: TransitionHistory,
  segmentId: string,
  transition: TransitionKind | null,
  durationSeconds: number | null,
): TransitionHistory {
  const present = setTransition(history.present, segmentId, transition, durationSeconds);
  return {
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: TransitionHistory): TransitionHistory {
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

export function redo(history: TransitionHistory): TransitionHistory {
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
