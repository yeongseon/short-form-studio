/**
 * SegmentTrimEditor — trim a segment's source edges through shared commands,
 * validated against source-media bounds, with undo/redo.
 *
 * The trim model is pure: applyTrim validates an edge change against the source
 * bounds (start >= 0, end <= source duration, start < end so the effective
 * timeline duration stays positive) and either returns the new TrimState or,
 * on a history, pushes it so undo/redo work. Keeping trimEnd - trimStart as the
 * effective duration is what preserves timeline/source consistency and
 * preview/render parity. The component emits a trimSegment EditorCommand rather
 * than mutating anything directly, and surfaces invalid trims as an error
 * without emitting.
 */

import { useState } from "react";

// --------------- pure trim model ---------------

export interface TrimState {
  sourceDurationSeconds: number;
  trimStartSeconds: number;
  trimEndSeconds: number;
}

export interface TrimEdit {
  edge: "start" | "end";
  seconds: number;
}

export interface TrimHistory {
  past: TrimState[];
  present: TrimState;
  future: TrimState[];
  canUndo: boolean;
  canRedo: boolean;
}

function nextTrim(state: TrimState, edit: TrimEdit): TrimState {
  const candidate: TrimState =
    edit.edge === "start"
      ? { ...state, trimStartSeconds: edit.seconds }
      : { ...state, trimEndSeconds: edit.seconds };

  if (candidate.trimStartSeconds < 0) {
    throw new RangeError("trim start must be >= 0 (first frame)");
  }
  if (candidate.trimEndSeconds > candidate.sourceDurationSeconds + 1e-9) {
    throw new RangeError("trim end must be <= source duration (last frame)");
  }
  if (candidate.trimStartSeconds >= candidate.trimEndSeconds) {
    throw new RangeError("trim start must be < trim end (positive duration)");
  }
  return candidate;
}

function isHistory(value: TrimState | TrimHistory): value is TrimHistory {
  return "present" in value;
}

/**
 * Apply a trim edge edit. Accepts a bare TrimState (returns the validated next
 * state) or a TrimHistory (pushes the validated state and returns new history).
 * Throws RangeError on an out-of-bounds or non-positive-duration trim.
 */
export function applyTrim(state: TrimState, edit: TrimEdit): TrimState;
export function applyTrim(history: TrimHistory, edit: TrimEdit): TrimHistory;
export function applyTrim(
  value: TrimState | TrimHistory,
  edit: TrimEdit,
): TrimState | TrimHistory {
  if (isHistory(value)) {
    const present = nextTrim(value.present, edit);
    const past = [...value.past, value.present];
    return { past, present, future: [], canUndo: true, canRedo: false };
  }
  return nextTrim(value, edit);
}

export function createTrimHistory(initial: TrimState): TrimHistory {
  return { past: [], present: initial, future: [], canUndo: false, canRedo: false };
}

export function undo(history: TrimHistory): TrimHistory {
  if (history.past.length === 0) {
    return history;
  }
  const previous = history.past[history.past.length - 1];
  const past = history.past.slice(0, -1);
  const future = [history.present, ...history.future];
  return {
    past,
    present: previous,
    future,
    canUndo: past.length > 0,
    canRedo: true,
  };
}

export function redo(history: TrimHistory): TrimHistory {
  if (history.future.length === 0) {
    return history;
  }
  const next = history.future[0];
  const future = history.future.slice(1);
  const past = [...history.past, history.present];
  return {
    past,
    present: next,
    future,
    canUndo: true,
    canRedo: future.length > 0,
  };
}

export type TrimCommand = {
  type: "trimSegment";
  segmentId: string;
  trimStartSeconds: number;
  trimEndSeconds: number;
};

// --------------- component ---------------

export interface SegmentTrimEditorProps {
  segmentId: string;
  sourceDurationSeconds: number;
  trimStartSeconds: number;
  trimEndSeconds: number;
  onCommand?: (command: TrimCommand) => void;
}

export default function SegmentTrimEditor({
  segmentId,
  sourceDurationSeconds,
  trimStartSeconds,
  trimEndSeconds,
  onCommand,
}: SegmentTrimEditorProps) {
  const [error, setError] = useState<string | null>(null);
  const base: TrimState = { sourceDurationSeconds, trimStartSeconds, trimEndSeconds };

  const edit = (edge: "start" | "end", raw: string) => {
    const seconds = Number(raw);
    if (Number.isNaN(seconds)) {
      setError("Invalid number");
      return;
    }
    try {
      const next = applyTrim(base, { edge, seconds });
      setError(null);
      onCommand?.({
        type: "trimSegment",
        segmentId,
        trimStartSeconds: next.trimStartSeconds,
        trimEndSeconds: next.trimEndSeconds,
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Invalid trim");
    }
  };

  const effective = trimEndSeconds - trimStartSeconds;

  return (
    <div
      data-testid="segment-trim-editor"
      data-status={error === null ? "ok" : "error"}
      data-trim-start={String(trimStartSeconds)}
      data-trim-end={String(trimEndSeconds)}
    >
      <label>
        Start
        <input
          data-testid="trim-start-input"
          type="number"
          min={0}
          max={sourceDurationSeconds}
          step={0.1}
          defaultValue={trimStartSeconds}
          onChange={(e) => edit("start", e.target.value)}
        />
      </label>
      <label>
        End
        <input
          data-testid="trim-end-input"
          type="number"
          min={0}
          max={sourceDurationSeconds}
          step={0.1}
          defaultValue={trimEndSeconds}
          onChange={(e) => edit("end", e.target.value)}
        />
      </label>
      <span data-testid="trim-effective-duration">{effective.toFixed(1)}s</span>
      {error !== null && <span data-testid="trim-error">{error}</span>}
    </div>
  );
}
