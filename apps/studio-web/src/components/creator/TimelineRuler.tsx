/**
 * TimelineRuler — readable time ticks synchronized with a Timeline's duration
 * and horizontal position.
 *
 * Tick placement is a pure function of duration + pixel width (computeTicks), so
 * it is deterministic and unit-testable. The interval adapts to the duration
 * (chooseTickInterval) to keep ticks readable for 15/30/45/60/90-second and
 * custom drafts, with no short-only duration ceiling. The ruler exposes the
 * total duration via role="img" + aria-label for accessible time information.
 */

// --------------- pure tick model ---------------

export interface RulerTick {
  seconds: number;
  x: number;
  label: string;
}

/** Format seconds as M:SS (e.g. 90 -> "1:30", 37 -> "0:37"). */
function formatClock(seconds: number): string {
  const whole = Math.floor(seconds);
  const mins = Math.floor(whole / 60);
  const secs = whole % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Choose a readable tick interval (seconds) for a given total duration. Steps
 * ascend so short drafts get fine ticks and long custom timelines stay legible;
 * always positive so tiny/zero durations still produce a valid interval.
 */
export function chooseTickInterval(durationSeconds: number): number {
  const steps = [5, 10, 15, 30, 60, 120, 300, 600];
  const targetTickCount = 8;
  if (durationSeconds <= 0) {
    return steps[0];
  }
  for (const step of steps) {
    if (durationSeconds / step <= targetTickCount) {
      return step;
    }
  }
  // Beyond the largest predefined step, scale to keep the tick count bounded.
  return Math.ceil(durationSeconds / targetTickCount / 300) * 300;
}

/**
 * Compute evenly spaced ticks from 0..duration, positioned by horizontal
 * fraction of the pixel width. Always includes an origin tick and an exact
 * end tick at the duration; zero/negative durations yield a single origin tick.
 */
export function computeTicks(durationSeconds: number, width: number): RulerTick[] {
  if (durationSeconds <= 0) {
    return [{ seconds: 0, x: 0, label: formatClock(0) }];
  }
  const interval = chooseTickInterval(durationSeconds);
  const ticks: RulerTick[] = [];
  for (let s = 0; s < durationSeconds; s += interval) {
    ticks.push({
      seconds: s,
      x: (s / durationSeconds) * width,
      label: formatClock(s),
    });
  }
  ticks.push({
    seconds: durationSeconds,
    x: width,
    label: formatClock(durationSeconds),
  });
  return ticks;
}

// --------------- component ---------------

export interface TimelineRulerProps {
  durationSeconds: number;
  width: number;
}

export default function TimelineRuler({ durationSeconds, width }: TimelineRulerProps) {
  const ticks = computeTicks(durationSeconds, width);
  return (
    <div
      data-testid="timeline-ruler"
      data-duration={String(durationSeconds)}
      role="img"
      aria-label={`Timeline ruler, total duration ${formatClock(durationSeconds)} (${durationSeconds} seconds)`}
      style={{ position: "relative", width, height: 28, userSelect: "none" }}
    >
      {ticks.map((tick) => (
        <div
          key={tick.seconds}
          data-testid="ruler-tick"
          data-seconds={String(tick.seconds)}
          style={{
            position: "absolute",
            left: tick.x,
            top: 0,
            transform: "translateX(-50%)",
            fontSize: 10,
            color: "#8a8a8a",
            whiteSpace: "nowrap",
          }}
        >
          <span
            style={{
              display: "block",
              width: 1,
              height: 8,
              margin: "0 auto 2px",
              background: "#555",
            }}
          />
          {tick.label}
        </div>
      ))}
    </div>
  );
}
