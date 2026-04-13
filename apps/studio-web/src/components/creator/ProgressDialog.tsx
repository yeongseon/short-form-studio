/**
 * ProgressDialog — modal overlay that polls a pipeline run and shows
 * real-time stage / status while a long-running generation step proceeds.
 *
 * Props:
 * - open:          Whether the dialog is visible.
 * - runId:         Pipeline run to poll.
 * - expectedStage: The *_GENERATING stage we expect to see.
 *                  The dialog resolves (calls onComplete) once the stage
 *                  transitions past this value.
 * - apiBase:       API base URL (default "/api/creator").
 * - pollInterval:  Milliseconds between polls (default 3000).
 * - onComplete:    Called when the run moves past expectedStage (success path).
 * - onFailed:      Called when the run status becomes "failed".
 * - onClose:       Called when the user manually dismisses the dialog.
 */

import { useState, useEffect, useRef, useCallback, useId } from "react";

const DEFAULT_API = "/api/creator";
const DEFAULT_POLL_MS = 3000;

// --------------- types ---------------

export interface ProgressDialogProps {
  open: boolean;
  runId: number;
  expectedStage: string;
  apiBase?: string;
  pollInterval?: number;
  onComplete?: (stage: string, status: string) => void;
  onFailed?: (stage: string, status: string) => void;
  onClose?: () => void;
}

interface RunSnapshot {
  current_stage: string;
  status: string;
}

type Outcome = "running" | "completed" | "failed" | "error";

// Friendly labels for stages
const STAGE_LABELS: Record<string, string> = {
  SCRIPT_GENERATING: "Generating script…",
  VISUAL_PLAN_GENERATING: "Generating visual plan…",
  VISUAL_ASSET_GENERATING: "Generating visual assets…",
  AUDIO_GENERATING: "Generating audio…",
  SUBTITLE_GENERATING: "Generating subtitles…",
  RENDER_GENERATING: "Rendering video…",
};

// --------------- component ---------------

export default function ProgressDialog({
  open,
  runId,
  expectedStage,
  apiBase = DEFAULT_API,
  pollInterval = DEFAULT_POLL_MS,
  onComplete,
  onFailed,
  onClose,
}: ProgressDialogProps) {
  const [snapshot, setSnapshot] = useState<RunSnapshot | null>(null);
  const [outcome, setOutcome] = useState<Outcome>("running");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const descId = useId();

  // ---- classify run state ----

  const classify = useCallback(
    (run: RunSnapshot): Outcome => {
      if (run.status === "failed") return "failed";
      // If stage moved past expectedStage, generation completed
      if (run.current_stage !== expectedStage) return "completed";
      return "running";
    },
    [expectedStage],
  );

  // ---- poll loop ----

  useEffect(() => {
    if (!open) {
      // Reset when closed
      setSnapshot(null);
      setOutcome("running");
      setErrorMsg(null);
      setPollCount(0);
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    let cancelled = false;

    const poll = async () => {
      try {
        const res = await fetch(`${apiBase}/runs/${runId}`);
        if (cancelled) return;
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          setErrorMsg(body?.detail ?? `Poll failed (${res.status})`);
          setOutcome("error");
          return;
        }
        const data: RunSnapshot = await res.json();
        if (cancelled) return;
        setSnapshot(data);
        setPollCount((c) => c + 1);
        setErrorMsg(null);

        const result = classify(data);
        if (result === "completed") {
          setOutcome("completed");
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          onComplete?.(data.current_stage, data.status);
        } else if (result === "failed") {
          setOutcome("failed");
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
          onFailed?.(data.current_stage, data.status);
        }
      } catch (err) {
        if (cancelled) return;
        setErrorMsg(err instanceof Error ? err.message : "Network error");
        setOutcome("error");
      }
    };

    // Initial poll immediately
    poll();
    timerRef.current = setInterval(poll, pollInterval);

    return () => {
      cancelled = true;
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [open, runId, apiBase, pollInterval, classify, onComplete, onFailed]);

  // ---- focus management + Escape handler ----

  useEffect(() => {
    if (!open) return;

    // Store previously focused element to restore on close
    previousFocusRef.current = document.activeElement as HTMLElement | null;

    // Focus the close button on open
    const dialog = dialogRef.current;
    if (dialog) {
      const closeBtn = dialog.querySelector<HTMLElement>("button[data-testid='progress-close']");
      closeBtn?.focus();
    }

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        return;
      }

      // Focus trap: keep Tab within dialog
      if (e.key === "Tab" && dialog) {
        const focusable = dialog.querySelectorAll<HTMLElement>("button:not([disabled])");
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      // Restore focus
      previousFocusRef.current?.focus();
    };
  }, [open, onClose]);

  // ---- don't render when closed ----

  if (!open) return null;

  // ---- derived display values ----

  const stageLabel =
    snapshot?.current_stage
      ? STAGE_LABELS[snapshot.current_stage] ?? snapshot.current_stage
      : STAGE_LABELS[expectedStage] ?? expectedStage;

  const statusText = snapshot?.status ?? "starting";

  const isTerminal = outcome === "completed" || outcome === "failed" || outcome === "error";

  // ---- render ----

  return (
    <div
      data-testid="progress-dialog-overlay"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        ref={dialogRef}
        data-testid="progress-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        style={{
          background: "#fff",
          borderRadius: 12,
          padding: "32px 40px",
          minWidth: 360,
          maxWidth: 480,
          boxShadow: "0 8px 30px rgba(0,0,0,0.2)",
          textAlign: "center",
        }}
      >
        {/* Stage label */}
        <h3
          id={titleId}
          data-testid="progress-stage"
          style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 600, color: "#111827" }}
        >
          {stageLabel}
        </h3>

        {/* Status line */}
        <p
          id={descId}
          data-testid="progress-status"
          style={{ margin: "0 0 16px", fontSize: 13, color: "#6b7280" }}
        >
          Status: {statusText}
        </p>

        {/* Animated indicator (running only) */}
        {outcome === "running" && (
          <div
            data-testid="progress-spinner"
            style={{
              width: 40,
              height: 40,
              margin: "0 auto 16px",
              border: "3px solid #e5e7eb",
              borderTop: "3px solid #4285f4",
              borderRadius: "50%",
              animation: "spin 1s linear infinite",
            }}
          />
        )}

        {/* Success state */}
        {outcome === "completed" && (
          <div
            data-testid="progress-completed"
            style={{
              margin: "0 0 16px",
              padding: "8px 16px",
              background: "#f0fdf4",
              border: "1px solid #bbf7d0",
              borderRadius: 6,
              color: "#166534",
              fontSize: 13,
            }}
          >
            Generation complete — moved to {snapshot?.current_stage}
          </div>
        )}

        {/* Failed state */}
        {outcome === "failed" && (
          <div
            data-testid="progress-failed"
            style={{
              margin: "0 0 16px",
              padding: "8px 16px",
              background: "#fef2f2",
              border: "1px solid #fca5a5",
              borderRadius: 6,
              color: "#b91c1c",
              fontSize: 13,
            }}
          >
            Generation failed
          </div>
        )}

        {/* Network error state */}
        {outcome === "error" && errorMsg && (
          <div
            data-testid="progress-error"
            style={{
              margin: "0 0 16px",
              padding: "8px 16px",
              background: "#fffbeb",
              border: "1px solid #fde68a",
              borderRadius: 6,
              color: "#92400e",
              fontSize: 13,
            }}
          >
            {errorMsg}
          </div>
        )}

        {/* Poll count (subtle, for debugging) */}
        <p
          data-testid="progress-poll-count"
          style={{ margin: "0 0 16px", fontSize: 11, color: "#9ca3af" }}
        >
          {pollCount} poll{pollCount !== 1 ? "s" : ""}
        </p>

        {/* Close / Dismiss button */}
        <button
          data-testid="progress-close"
          onClick={onClose}
          style={{
            padding: "8px 24px",
            border: "1px solid #d1d5db",
            borderRadius: 6,
            background: isTerminal ? "#4285f4" : "#fff",
            color: isTerminal ? "#fff" : "#374151",
            cursor: "pointer",
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          {isTerminal ? "Close" : "Dismiss"}
        </button>
      </div>

      {/* Keyframe for spinner */}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
