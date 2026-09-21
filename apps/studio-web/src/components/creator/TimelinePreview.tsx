/**
 * TimelinePreview — browser preview of a compiled Timeline RenderPlan.
 *
 * Previews the same RenderPlan the renderer consumes (fetched from the preview
 * endpoint), so what the user sees is what gets rendered. Provides playback,
 * seek, and aspect handling with deterministic timing: the displayed segment is
 * a pure function of currentTime via segmentAtTime(), so timing does not depend
 * on wall-clock in the mapping (rAF only advances currentTime during playback).
 *
 * Three states via data-status: loading, error, ready.
 */

import { useEffect, useRef, useState } from "react";

import {
  fetchTimelinePreview,
  type RenderPlan,
  type RenderSegment,
} from "../../api/timelinePreview";

export interface TimelinePreviewProps {
  projectId: number;
  output?: string;
  encoding?: string;
}

/** Total timeline duration = furthest segment end. */
export function totalDuration(plan: RenderPlan): number {
  return plan.segments.reduce(
    (max, s) => Math.max(max, s.timeline_start_seconds + s.duration_seconds),
    0,
  );
}

/**
 * Pure mapping from a playhead time to the active segment. A segment owns the
 * half-open window [start, start + duration); a boundary belongs to the next
 * segment, and times past the end return null. Segments are ordered and
 * non-overlapping (enforced by the domain), so the first match wins.
 */
export function segmentAtTime(plan: RenderPlan, t: number): RenderSegment | null {
  for (const seg of plan.segments) {
    const start = seg.timeline_start_seconds;
    const end = start + seg.duration_seconds;
    if (t >= start && t < end) {
      return seg;
    }
  }
  return null;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; plan: RenderPlan };

export default function TimelinePreview({
  projectId,
  output,
  encoding,
}: TimelinePreviewProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    fetchTimelinePreview(projectId, { output, encoding })
      .then((plan) => {
        if (!cancelled) {
          setState({ status: "ready", plan });
          setCurrentTime(0);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load preview";
          setState({ status: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, output, encoding]);

  const total = state.status === "ready" ? totalDuration(state.plan) : 0;

  useEffect(() => {
    if (!playing || state.status !== "ready") {
      return;
    }
    const step = (ts: number) => {
      if (lastTsRef.current !== null) {
        const delta = (ts - lastTsRef.current) / 1000;
        setCurrentTime((prev) => {
          const next = prev + delta;
          if (next >= total) {
            setPlaying(false);
            return total;
          }
          return next;
        });
      }
      lastTsRef.current = ts;
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
      }
      lastTsRef.current = null;
    };
  }, [playing, state, total]);

  if (state.status === "loading") {
    return (
      <div data-testid="timeline-preview" data-status="loading">
        Loading preview…
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div data-testid="timeline-preview" data-status="error">
        {state.message}
      </div>
    );
  }

  const { plan } = state;
  const active = segmentAtTime(plan, currentTime);
  const { width, height } = plan.output_spec;

  return (
    <div data-testid="timeline-preview" data-status="ready">
      <div
        data-testid="preview-stage"
        data-aspect={`${width}x${height}`}
        style={{
          aspectRatio: `${width} / ${height}`,
          maxWidth: "100%",
          background: "#000",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
        }}
      >
        {active === null ? (
          <div data-testid="preview-empty">No content at this time</div>
        ) : active.kind === "image" ? (
          <img
            data-testid="preview-media"
            src={active.source}
            alt=""
            style={{
              width: "100%",
              height: "100%",
              objectFit: active.fit_mode === "contain" ? "contain" : "cover",
            }}
          />
        ) : (
          <video
            data-testid="preview-media"
            src={active.source}
            muted
            style={{
              width: "100%",
              height: "100%",
              objectFit: active.fit_mode === "contain" ? "contain" : "cover",
            }}
          />
        )}
      </div>

      <div>
        <button
          type="button"
          data-testid="preview-play-toggle"
          data-playing={playing ? "true" : "false"}
          onClick={() => setPlaying((p) => !p)}
        >
          {playing ? "Pause" : "Play"}
        </button>
        <input
          type="range"
          role="slider"
          data-testid="preview-seek"
          min={0}
          max={total}
          step={0.1}
          value={currentTime}
          onChange={(e) => {
            setPlaying(false);
            setCurrentTime(Number(e.target.value));
          }}
        />
        <span data-testid="preview-time">
          {currentTime.toFixed(1)} / {total.toFixed(1)}
        </span>
      </div>

      {(plan.narration_path !== null || plan.music_path !== null) && (
        <audio
          data-testid="preview-audio-layer"
          src={plan.narration_path ?? plan.music_path ?? undefined}
          muted
          hidden
        />
      )}
      {plan.subtitle_path !== null && (
        <div data-testid="preview-caption-indicator">Captions</div>
      )}
    </div>
  );
}
