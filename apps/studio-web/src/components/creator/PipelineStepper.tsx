/**
 * PipelineStepper — compact visual indicator of pipeline progress.
 *
 * Groups backend RunStage values into 6 user-facing steps and renders them
 * as a horizontal stepper with distinct completed / current / pending / failed
 * states.  Accepts run status as props; does NOT own any fetch logic.
 */

/** User-facing pipeline steps in display order. */
export const PIPELINE_STEPS = [
  { key: "idea", label: "Idea" },
  { key: "script", label: "Script" },
  { key: "visual_plan", label: "Visual Plan" },
  { key: "assets", label: "Assets" },
  { key: "audio_subtitles", label: "Audio / Subs" },
  { key: "render", label: "Render" },
] as const;

export type StepKey = (typeof PIPELINE_STEPS)[number]["key"];

/**
 * Maps every backend RunStage string to the step key it belongs to.
 * Centralised here so the rest of the UI never deals with raw stage enums.
 */
export const STAGE_TO_STEP: Record<string, StepKey> = {
  IDEA_READY: "idea",
  SCRIPT_GENERATING: "script",
  SCRIPT_REVIEW: "script",
  VISUAL_PLAN_GENERATING: "visual_plan",
  VISUAL_PLAN_REVIEW: "visual_plan",
  VISUAL_ASSET_GENERATING: "assets",
  VISUAL_ASSET_REVIEW: "assets",
  AUDIO_GENERATING: "audio_subtitles",
  SUBTITLE_GENERATING: "audio_subtitles",
  RENDER_GENERATING: "render",
  FINAL_REVIEW: "render",
  PUBLISHED: "render",
};

// --------------- props ---------------

export interface PipelineStepperProps {
  /** Current backend stage string (e.g. "SCRIPT_REVIEW"). */
  currentStage: string;
  /** True when the run is in FAILED state. */
  failed?: boolean;
}

// --------------- styles ---------------

type StepStatus = "completed" | "current" | "pending" | "failed";

const COLORS: Record<StepStatus, { bg: string; border: string; text: string; label: string }> = {
  completed: { bg: "#d4edda", border: "#28a745", text: "#28a745", label: "#155724" },
  current: { bg: "#cce5ff", border: "#007bff", text: "#007bff", label: "#004085" },
  pending: { bg: "#f8f9fa", border: "#dee2e6", text: "#adb5bd", label: "#6c757d" },
  failed: { bg: "#f8d7da", border: "#dc3545", text: "#dc3545", label: "#721c24" },
};

const CONNECTOR_COMPLETED = "#28a745";
const CONNECTOR_DEFAULT = "#dee2e6";

// --------------- helpers ---------------

function resolveStepIndex(stage: string): number {
  const key = STAGE_TO_STEP[stage];
  if (!key) return -1;
  return PIPELINE_STEPS.findIndex((s) => s.key === key);
}

function getStepStatus(stepIdx: number, activeIdx: number, isFailed: boolean): StepStatus {
  if (isFailed && stepIdx === activeIdx) return "failed";
  if (stepIdx < activeIdx) return "completed";
  if (stepIdx === activeIdx) return "current";
  return "pending";
}

// --------------- component ---------------

export default function PipelineStepper({ currentStage, failed = false }: PipelineStepperProps) {
  const activeIdx = resolveStepIndex(currentStage);

  // For PUBLISHED, bump activeIdx past all steps so all show completed.
  const effectiveIdx = currentStage === "PUBLISHED" ? PIPELINE_STEPS.length : activeIdx;

  return (
    <nav aria-label="Pipeline progress" data-testid="pipeline-stepper">
      <ol
        style={{
          display: "flex",
          alignItems: "center",
          listStyle: "none",
          padding: 0,
          margin: 0,
          gap: 0,
        }}
      >
        {PIPELINE_STEPS.map((step, idx) => {
          const status = getStepStatus(idx, effectiveIdx, failed);
          const colors = COLORS[status];
          const isLast = idx === PIPELINE_STEPS.length - 1;

          return (
            <li
              key={step.key}
              style={{ display: "flex", alignItems: "center" }}
              data-testid={`step-${step.key}`}
              data-status={status}
            >
              {/* Circle + label */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  minWidth: 64,
                }}
              >
                <div
                  aria-current={status === "current" ? "step" : undefined}
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: "50%",
                    border: `2px solid ${colors.border}`,
                    backgroundColor: colors.bg,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 12,
                    fontWeight: status === "current" ? 700 : 500,
                    color: colors.text,
                  }}
                >
                  {status === "completed" ? "✓" : status === "failed" ? "✕" : idx + 1}
                </div>
                <span
                  style={{
                    marginTop: 4,
                    fontSize: 11,
                    color: colors.label,
                    fontWeight: status === "current" ? 600 : 400,
                    whiteSpace: "nowrap",
                  }}
                >
                  {step.label}
                </span>
              </div>

              {/* Connector line */}
              {!isLast && (
                <div
                  style={{
                    width: 32,
                    height: 2,
                    backgroundColor: idx < effectiveIdx ? CONNECTOR_COMPLETED : CONNECTOR_DEFAULT,
                    flexShrink: 0,
                  }}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
