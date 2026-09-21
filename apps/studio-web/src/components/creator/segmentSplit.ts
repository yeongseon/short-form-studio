/**
 * segmentSplit — pure model for splitting a timeline segment at a playhead
 * position into two stable segments, with undo/redo.
 *
 * splitSegment divides one segment at a timeline time into a left and right
 * half whose durations sum to the original (total timing preserved) and which
 * both keep the original scene association. For video sources it computes the
 * source offset so the right half continues in source time where the left ends
 * (correct trims); image sources carry no source offset. A split exactly at the
 * segment start or end, or outside its window, is rejected so neither half is
 * empty. applySplit replaces the target segment with its two halves atomically
 * over a SplitHistory so the whole operation is one undoable step.
 */

export type SplitKind = "image" | "video";

export interface SplittableSegment {
  id: string;
  sceneId: string;
  kind: SplitKind;
  source: string;
  timelineStartSeconds: number;
  durationSeconds: number;
  trimStartSeconds: number | null;
  trimEndSeconds: number | null;
}

export interface SplitHistory {
  past: SplittableSegment[][];
  present: SplittableSegment[];
  future: SplittableSegment[][];
  canUndo: boolean;
  canRedo: boolean;
}

/**
 * Split ``segment`` at timeline time ``atSeconds`` into [left, right]. Throws
 * RangeError when the split falls on or outside the segment boundaries (which
 * would produce an empty half).
 */
export function splitSegment(
  segment: SplittableSegment,
  atSeconds: number,
): [SplittableSegment, SplittableSegment] {
  const start = segment.timelineStartSeconds;
  const end = start + segment.durationSeconds;
  if (atSeconds <= start + 1e-9 || atSeconds >= end - 1e-9) {
    throw new RangeError(
      `split ${atSeconds} must fall strictly inside [${start}, ${end}]`,
    );
  }

  const leftDuration = atSeconds - start;
  const rightDuration = end - atSeconds;

  const sourceSplit =
    segment.kind === "video" && segment.trimStartSeconds !== null
      ? segment.trimStartSeconds + leftDuration
      : null;

  const left: SplittableSegment = {
    ...segment,
    id: `${segment.id}:a`,
    durationSeconds: leftDuration,
    trimEndSeconds: sourceSplit,
  };
  const right: SplittableSegment = {
    ...segment,
    id: `${segment.id}:b`,
    timelineStartSeconds: atSeconds,
    durationSeconds: rightDuration,
    trimStartSeconds: sourceSplit,
  };
  return [left, right];
}

export function createSplitHistory(segments: SplittableSegment[]): SplitHistory {
  return { past: [], present: segments, future: [], canUndo: false, canRedo: false };
}

export function applySplit(
  history: SplitHistory,
  segmentId: string,
  atSeconds: number,
): SplitHistory {
  const index = history.present.findIndex((s) => s.id === segmentId);
  if (index === -1) {
    throw new Error(`segment not found: ${segmentId}`);
  }
  const [left, right] = splitSegment(history.present[index], atSeconds);
  const present = [
    ...history.present.slice(0, index),
    left,
    right,
    ...history.present.slice(index + 1),
  ];
  return {
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: SplitHistory): SplitHistory {
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

export function redo(history: SplitHistory): SplitHistory {
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
