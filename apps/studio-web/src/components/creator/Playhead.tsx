/**
 * Playhead — visual playhead marker + accessible seek control synchronized with
 * playback time.
 *
 * Timing is drift-free: the playback clock derives currentTime from a wall-clock
 * anchor (anchorWallMs + anchorTime), NOT from accumulated frame deltas, so
 * repeated ticks at any cadence yield the exact same time (tickPlayback). Seeks
 * re-anchor (seekTo) so playback continues from the new position without a
 * jump-back or stale state. All times are clamped to [0, duration], so
 * play/pause/end and boundary seeks never escape range.
 */

// --------------- pure playback clock ---------------

export interface PlaybackState {
  playing: boolean;
  anchorWallMs: number;
  anchorTime: number;
  duration: number;
}

export interface PlaybackTick {
  currentTime: number;
  playing: boolean;
}

/** Clamp a time to [0, duration]. */
export function clampTime(t: number, duration: number): number {
  if (t < 0) {
    return 0;
  }
  if (t > duration) {
    return duration;
  }
  return t;
}

/**
 * Compute the current playhead time at wall-clock ``nowMs`` from the anchor.
 * Because the elapsed time is (nowMs - anchorWallMs), never an accumulator,
 * there is no cumulative drift regardless of tick cadence. At/after the end,
 * playback stops at the duration.
 */
export function tickPlayback(state: PlaybackState, nowMs: number): PlaybackTick {
  if (!state.playing) {
    return { currentTime: state.anchorTime, playing: false };
  }
  const elapsed = (nowMs - state.anchorWallMs) / 1000;
  const raw = state.anchorTime + elapsed;
  if (raw >= state.duration) {
    return { currentTime: state.duration, playing: false };
  }
  return { currentTime: clampTime(raw, state.duration), playing: true };
}

/**
 * Seek to ``target`` seconds, re-anchoring the clock at wall-clock ``nowMs`` so
 * playback (if playing) continues smoothly from the clamped target.
 */
export function seekTo(state: PlaybackState, target: number, nowMs: number): PlaybackState {
  return {
    ...state,
    anchorTime: clampTime(target, state.duration),
    anchorWallMs: nowMs,
  };
}

// --------------- component ---------------

export interface PlayheadProps {
  currentTime: number;
  durationSeconds: number;
  width: number;
  /** Step for keyboard ArrowLeft/ArrowRight seeks (seconds). */
  stepSeconds?: number;
  onSeek?: (seconds: number) => void;
}

export default function Playhead({
  currentTime,
  durationSeconds,
  width,
  stepSeconds = 1,
  onSeek,
}: PlayheadProps) {
  const clamped = clampTime(currentTime, durationSeconds);
  const fraction = durationSeconds > 0 ? clamped / durationSeconds : 0;
  const left = fraction * width;

  const emit = (target: number) => {
    onSeek?.(clampTime(target, durationSeconds));
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    switch (event.key) {
      case "ArrowRight":
        event.preventDefault();
        emit(clamped + stepSeconds);
        break;
      case "ArrowLeft":
        event.preventDefault();
        emit(clamped - stepSeconds);
        break;
      case "Home":
        event.preventDefault();
        emit(0);
        break;
      case "End":
        event.preventDefault();
        emit(durationSeconds);
        break;
      default:
        break;
    }
  };

  return (
    <div
      data-testid="playhead"
      style={{ position: "relative", width, height: 24 }}
    >
      <div
        data-testid="playhead-marker"
        style={{
          position: "absolute",
          left,
          top: 0,
          width: 2,
          height: "100%",
          background: "#e5484d",
          transform: "translateX(-1px)",
          pointerEvents: "none",
        }}
      />
      <input
        type="range"
        data-testid="playhead-slider"
        role="slider"
        aria-label="Playhead"
        aria-valuemin={0}
        aria-valuemax={durationSeconds}
        aria-valuenow={clamped}
        min={0}
        max={durationSeconds}
        step={0.01}
        value={clamped}
        onChange={(e) => emit(Number(e.target.value))}
        onKeyDown={onKeyDown}
        style={{ position: "absolute", inset: 0, width: "100%", opacity: 0, cursor: "pointer" }}
      />
    </div>
  );
}
