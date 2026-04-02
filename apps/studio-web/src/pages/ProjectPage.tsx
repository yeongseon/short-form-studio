/**
 * ProjectPage — main working page for a short-form video project.
 *
 * Loads the project detail and its latest run, then renders:
 * - PipelineStepper (header progress bar)
 * - ScriptComposer (during script stages: IDEA_READY, SCRIPT_GENERATING, SCRIPT_REVIEW)
 * - VisualPlanEditor section (during visual plan stages)
 * - StoryboardWorkspace (post visual-plan: scene-centric card grid)
 * - Final review section with preview summary and review-page link
 * - ConfirmDialog for stop / resume / delete
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";

import PipelineStepper from "../components/creator/PipelineStepper";
import ScriptComposer from "../components/creator/ScriptComposer";
import StoryboardWorkspace from "../components/creator/StoryboardWorkspace";
import VisualPlanEditor from "../components/creator/VisualPlanEditor";
import ModelSelector from "../components/creator/ModelSelector";
import ConfirmDialog from "../components/creator/ConfirmDialog";

const API_BASE = "/api/creator";

// --------------- types ---------------

interface ProjectDetail {
  id: number;
  title: string | null;
  source_type: string;
  status: string;
  idea_brief?: string | null;
  markdown_source?: string | null;
  url_source?: string | null;
  latest_run?: {
    run_id: number;
    current_stage: string | null;
    status: string | null;
  } | null;
}

interface ModelDefaults {
  script_model?: string;
  image_model?: string;
  tts_model?: string;
  subtitle_model?: string;
  render_profile?: string;
}

interface RunDetail {
  id: number;
  project_id: number;
  current_stage: string;
  status: string;
  restart_from: string | null;
  model_defaults: ModelDefaults | null;
}

type EditorMode = "markdown" | "structured";

// Script stages where ScriptComposer is shown
const SCRIPT_STAGES = new Set(["SCRIPT_GENERATING", "SCRIPT_REVIEW"]);

// Visual plan stages where the editor area is relevant
const VISUAL_PLAN_STAGES = new Set([
  "VISUAL_PLAN_SETUP",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_PLAN_REVIEW",
]);

// Visual asset stages
const VISUAL_ASSET_STAGES = new Set([
  "VISUAL_ASSET_GENERATING",
  "VISUAL_ASSET_REVIEW",
]);

// Audio stage
const AUDIO_STAGES = new Set(["AUDIO_GENERATING"]);

// Subtitle stage
const SUBTITLE_STAGES = new Set(["SUBTITLE_GENERATING"]);

// Render stage
const RENDER_STAGES = new Set(["RENDER_GENERATING"]);

// Final review
const FINAL_REVIEW_STAGES = new Set(["FINAL_REVIEW"]);

// All stages handled by StoryboardWorkspace (scene-centric view)
const STORYBOARD_WORKSPACE_STAGES = new Set([
  "VISUAL_ASSET_GENERATING",
  "VISUAL_ASSET_REVIEW",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

// Stages where we poll run status
const RUN_POLL_STAGES = new Set([
  "SCRIPT_GENERATING",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_ASSET_GENERATING",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
]);

// Stages where editing is allowed (not generating)
const EDITABLE_STAGES = new Set(["SCRIPT_REVIEW", "VISUAL_PLAN_REVIEW"]);

// Back navigation labels per review stage
const STAGE_BACK_LABELS: Record<string, string> = {
  SCRIPT_REVIEW: "\u2190 Back to Idea",
  VISUAL_PLAN_SETUP: "\u2190 Back to Script Review",
  VISUAL_PLAN_REVIEW: "\u2190 Back to Visual Plan Setup",
  VISUAL_ASSET_REVIEW: "\u2190 Back to Visual Plan",
  FINAL_REVIEW: "\u2190 Back to Visual Assets",
};

// SD quality presets for image generation tuning
const SD_QUALITY_PRESETS: Record<
  string,
  { steps: number; cfg_scale: number; sampler_name: string; label: string; description: string }
> = {
  fast: {
    steps: 15,
    cfg_scale: 5,
    sampler_name: "Euler a",
    label: "\u26a1 Fast Preview",
    description: "Quick preview, lower quality (15 steps)",
  },
  balanced: {
    steps: 25,
    cfg_scale: 7,
    sampler_name: "DPM++ 2M Karras",
    label: "\u2696\ufe0f Balanced",
    description: "Good quality/speed balance (25 steps)",
  },
  high: {
    steps: 40,
    cfg_scale: 8,
    sampler_name: "DPM++ 2M Karras",
    label: "\u2728 High Quality",
    description: "Best quality, slower (40 steps)",
  },
};

const SD_SAMPLERS = [
  "DPM++ 2M Karras",
  "DPM++ SDE Karras",
  "DPM++ 2M SDE Karras",
  "DPM++ 2M",
  "DPM++ SDE",
  "DPM++ 2S a Karras",
  "Euler a",
  "Euler",
  "DDIM",
  "UniPC",
  "LMS Karras",
  "Heun",
];

const RENDER_PROFILE_OPTIONS = [
  { value: "shorts_default", label: "Shorts Default" },
  { value: "high_quality", label: "High Quality" },
  { value: "fast_preview", label: "Fast Preview" },
];

// --------------- Visual Plan Setup Cards ---------------

interface ScriptSection {
  section_id: string;
  type: string;
  text: string;
  display_text?: string;
  speaker?: string;
  duration?: number;
  turn_kind?: string;
}

function VisualPlanSetupCards({ runId }: { runId: number }) {
  const [sections, setSections] = useState<ScriptSection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/runs/${runId}/script/structured`);
        if (!res.ok) {
          throw new Error(`Failed to load script (${res.status})`);
        }
        const data = await res.json();
        setSections(data.sections ?? []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load script sections");
      } finally {
        setLoading(false);
      }
    })();
  }, [runId]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", padding: 24, color: "#6b7280" }}>
        Loading script sections\u2026
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          padding: 16,
          background: "#fef2f2",
          border: "1px solid #fca5a5",
          borderRadius: 8,
          color: "#b91c1c",
          fontSize: 13,
        }}
      >
        {error}
      </div>
    );
  }

  if (sections.length === 0) {
    return (
      <div style={{ textAlign: "center", padding: 24, color: "#6b7280" }}>
        No script sections found. Go back and generate a script first.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {sections.map((sec, idx) => (
        <div
          key={sec.section_id}
          style={{
            display: "flex",
            alignItems: "stretch",
            border: "1px solid #e5e7eb",
            borderRadius: 10,
            background: "#fff",
            overflow: "hidden",
            boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          }}
        >
          {/* Left: paragraph number badge */}
          <div
            style={{
              width: 52,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              background:
                sec.type === "narration"
                  ? "#eff6ff"
                  : sec.type === "dialogue"
                    ? "#fdf4ff"
                    : "#f0fdf4",
              borderRight: "1px solid #e5e7eb",
              padding: "12px 0",
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 11, color: "#6b7280", fontWeight: 500 }}>
              \u00a7{idx + 1}
            </span>
            <span
              style={{
                fontSize: 10,
                color:
                  sec.type === "narration"
                    ? "#2563eb"
                    : sec.type === "dialogue"
                      ? "#7c3aed"
                      : "#16a34a",
                fontWeight: 600,
                marginTop: 2,
                textTransform: "uppercase",
              }}
            >
              {sec.type}
            </span>
          </div>

          {/* Center: text */}
          <div style={{ flex: 1, padding: "12px 16px", minWidth: 0 }}>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                lineHeight: 1.55,
                color: "#1f2937",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {sec.display_text || sec.text}
            </p>
            {sec.speaker && (
              <span
                style={{
                  fontSize: 11,
                  color: "#9ca3af",
                  marginTop: 4,
                  display: "inline-block",
                }}
              >
                Speaker: {sec.speaker}
              </span>
            )}
          </div>

          {/* Right: image indicator */}
          <div
            style={{
              width: 80,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              background: "#faf5ff",
              borderLeft: "1px solid #e5e7eb",
              padding: "12px 0",
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 20 }}>{"\ud83d\uddbc\ufe0f"}</span>
            <span
              style={{ fontSize: 10, color: "#6b21a8", fontWeight: 600, marginTop: 4 }}
            >
              1 Image
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// --------------- Main Component ---------------

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();

  // Data state
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action loading states
  const [approving, setApproving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [restarting, setRestarting] = useState(false);

  // Stop / Resume / Delete states
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmAction, setConfirmAction] = useState<
    "stop" | "resume" | "delete" | null
  >(null);

  // Status toast
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Per-stage model selection (persisted to backend via model_defaults)
  const [modelSelection, setModelSelection] = useState<ModelDefaults>({});
  const [goingBack, setGoingBack] = useState(false);

  // Preview data for FINAL_REVIEW
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);

  // ---- data fetching ----

  const fetchProjectAndRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Fetch project
      const projRes = await fetch(`${API_BASE}/projects/${numericProjectId}`);
      if (!projRes.ok) {
        if (projRes.status === 404) throw new Error("Project not found");
        const body = await projRes.json().catch(() => null);
        throw new Error(
          body?.detail ?? `Failed to load project (${projRes.status})`,
        );
      }
      const projData: ProjectDetail = await projRes.json();
      setProject(projData);

      // 2. Fetch runs for this project (newest first), take the latest
      const runsRes = await fetch(
        `${API_BASE}/projects/${numericProjectId}/runs`,
      );
      if (runsRes.ok) {
        const runsData: { runs: RunDetail[]; total: number } =
          await runsRes.json();
        setRun(runsData.runs.length > 0 ? runsData.runs[0] : null);
      } else {
        setRun(null);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "An unexpected error occurred",
      );
    } finally {
      setLoading(false);
    }
  }, [numericProjectId]);

  useEffect(() => {
    if (!Number.isNaN(numericProjectId)) {
      fetchProjectAndRun();
    }
  }, [numericProjectId, fetchProjectAndRun]);

  useEffect(() => {
    if (!run || run.current_stage !== "FINAL_REVIEW") {
      setPreview(null);
      return;
    }
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/runs/${run.id}/preview`);
        if (res.ok) {
          const data = await res.json();
          setPreview(data);
        }
      } catch {
        // non-critical
      }
    })();
  }, [run]);

  // ---- refresh run ----

  const refreshRun = useCallback(async (runId: number) => {
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}`);
      if (res.ok) {
        const data: RunDetail = await res.json();
        setRun(data);
      }
    } catch {
      // silent — non-critical
    }
  }, []);

  useEffect(() => {
    if (!run || !RUN_POLL_STAGES.has(run.current_stage)) return;
    const timer = setInterval(() => {
      void refreshRun(run.id);
    }, 3000);
    return () => clearInterval(timer);
  }, [run, refreshRun]);

  // Initialize model selection from run.model_defaults on load
  useEffect(() => {
    if (run?.model_defaults) {
      setModelSelection((prev) => {
        const hasLocal = Object.keys(prev).length > 0;
        if (hasLocal) return prev;
        return { ...run.model_defaults } as ModelDefaults;
      });
    }
  }, [run?.model_defaults]);

  // Build a selectedModels map scoped to specific categories.
  const buildSelectedModels = useCallback(
    (categories: string[]): Record<string, string> | undefined => {
      const FIELD_TO_CAT: Record<string, string> = {
        script_model: "script",
        image_model: "image",
        tts_model: "tts",
        subtitle_model: "stt",
      };
      const catSet = new Set(categories);
      const map: Record<string, string> = {};
      for (const [field, cat] of Object.entries(FIELD_TO_CAT)) {
        if (
          catSet.has(cat) &&
          modelSelection[field as keyof ModelDefaults]
        ) {
          map[cat] = modelSelection[field as keyof ModelDefaults]!;
        }
      }
      return Object.keys(map).length > 0 ? map : undefined;
    },
    [modelSelection],
  );

  // Persist model selection to backend
  const handleModelChange = useCallback(
    (category: string, modelKey: string) => {
      const fieldMap: Record<string, keyof ModelDefaults> = {
        script: "script_model",
        image: "image_model",
        tts: "tts_model",
        stt: "subtitle_model",
        render: "render_profile",
      };
      const field = fieldMap[category];
      if (!field) return;
      setModelSelection((prev) => ({ ...prev, [field]: modelKey }));
      if (run) {
        fetch(`${API_BASE}/runs/${run.id}/model-defaults`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: modelKey }),
        }).catch(() => {
          /* non-critical */
        });
      }
    },
    [run],
  );

  // ---- go-back navigation ----

  const handleGoBack = useCallback(async () => {
    if (!run) return;
    setGoingBack(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/go-back`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Go back failed (${res.status})`);
      }
      setStatusMessage("Navigated back");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Go back failed");
    } finally {
      setGoingBack(false);
    }
  }, [run, refreshRun]);

  // ---- script actions ----

  const handleApprove = useCallback(async () => {
    if (!run) return;
    setApproving(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/approve-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Approve failed (${res.status})`);
      }
      setStatusMessage("Script approved");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setApproving(false);
    }
  }, [run, refreshRun]);

  const handleGenerate = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/generate-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${res.status})`);
      }
      setStatusMessage("Script generation started");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Generate failed",
      );
    } finally {
      setGenerating(false);
    }
  }, [run, refreshRun, modelSelection.script_model]);

  const handleRestart = useCallback(async () => {
    if (!run) return;
    setRestarting(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "SCRIPT_GENERATING" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${res.status})`);
      }
      setStatusMessage("Restarting script generation\u2026");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Restart failed",
      );
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun]);

  // ---- visual plan actions ----

  const handleApproveVisualPlan = useCallback(async () => {
    if (!run) return;
    setApproving(true);
    setStatusMessage(null);
    try {
      const res = await fetch(
        `${API_BASE}/runs/${run.id}/approve-visual-plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewer: "agent" }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Approve failed (${res.status})`);
      }
      setStatusMessage("Visual plan approved");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setApproving(false);
    }
  }, [run, refreshRun]);

  const handleGenerateVisualPlan = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(
        `${API_BASE}/runs/${run.id}/generate-visual-plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model_key: modelSelection.script_model || "qwen3-4b",
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${res.status})`);
      }
      setStatusMessage("Visual plan generation started");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Generate failed",
      );
    } finally {
      setGenerating(false);
    }
  }, [run, refreshRun, modelSelection.script_model]);

  const handleRestartVisualPlan = useCallback(async () => {
    if (!run) return;
    setRestarting(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "VISUAL_PLAN_GENERATING" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${res.status})`);
      }
      setStatusMessage("Restarting visual plan generation\u2026");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Restart failed",
      );
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun]);

  // ---- visual asset actions (kept for StoryboardWorkspace internal use) ----

  const handleGenerateAllAssets = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(
        `${API_BASE}/runs/${run.id}/generate-visual-assets`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model_key: modelSelection.image_model || "sd15",
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          body?.detail ?? `Generate assets failed (${res.status})`,
        );
      }
      setStatusMessage("Visual asset generation started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Generate assets failed",
      );
    } finally {
      setGenerating(false);
    }
  }, [run, modelSelection.image_model]);

  const handleApproveAssets = useCallback(async () => {
    if (!run) return;
    setApproving(true);
    setStatusMessage(null);
    try {
      const res = await fetch(
        `${API_BASE}/runs/${run.id}/approve-visual-assets`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reviewer: "agent" }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Approve failed (${res.status})`);
      }
      setStatusMessage("Visual assets approved");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Approve assets failed",
      );
    } finally {
      setApproving(false);
    }
  }, [run, refreshRun]);

  const handleRestartAssets = useCallback(async () => {
    if (!run) return;
    setRestarting(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "VISUAL_ASSET_GENERATING" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${res.status})`);
      }
      setStatusMessage("Restarting visual asset generation\u2026");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Restart failed",
      );
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun]);

  // ---- audio actions ----

  const handleGenerateAudio = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/generate-audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tts_model: modelSelection.tts_model || "qwen3-tts",
          voice: "default",
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          body?.detail ?? `Generate audio failed (${res.status})`,
        );
      }
      setStatusMessage("Audio generation started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Generate audio failed",
      );
    } finally {
      setGenerating(false);
    }
  }, [run, modelSelection.tts_model]);

  // ---- subtitle actions ----

  const handleGenerateSubtitles = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(
        `${API_BASE}/runs/${run.id}/generate-subtitles`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subtitle_model: modelSelection.subtitle_model || "whisper-small",
            subtitle_format: "srt",
          }),
        },
      );
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          body?.detail ?? `Generate subtitles failed (${res.status})`,
        );
      }
      setStatusMessage("Subtitle generation started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(
        err instanceof Error ? err.message : "Generate subtitles failed",
      );
    } finally {
      setGenerating(false);
    }
  }, [run, modelSelection.subtitle_model]);

  // ---- render actions ----

  const handleRender = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          render_profile: modelSelection.render_profile || "shorts_default",
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Render failed (${res.status})`);
      }
      setStatusMessage("Render started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Render failed");
    } finally {
      setGenerating(false);
    }
  }, [run, modelSelection.render_profile]);

  // ---- stop / resume / delete actions ----

  const handleStop = useCallback(async () => {
    if (!run) return;
    setStopping(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/stop`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Stop failed (${res.status})`);
      }
      setStatusMessage("Run stopped");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Stop failed");
    } finally {
      setStopping(false);
    }
  }, [run, refreshRun]);

  const handleResume = useCallback(async () => {
    if (!run) return;
    setResuming(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/resume`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Resume failed (${res.status})`);
      }
      setStatusMessage("Run resumed");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Resume failed");
    } finally {
      setResuming(false);
    }
  }, [run, refreshRun]);

  const handleDeleteProject = useCallback(async () => {
    setDeleting(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/projects/${numericProjectId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Delete failed (${res.status})`);
      }
      navigate("/runs");
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  }, [numericProjectId, navigate]);

  // ---- derived state ----

  const currentStage = run?.current_stage ?? "IDEA_READY";
  const isFailed = run?.status === "failed";
  const isScriptStage = SCRIPT_STAGES.has(currentStage);
  const isScriptWorkspace = currentStage === "IDEA_READY" || isScriptStage;
  const isVisualPlanStage = VISUAL_PLAN_STAGES.has(currentStage);
  const isStoryboardWorkspace = STORYBOARD_WORKSPACE_STAGES.has(currentStage);
  const isVPGenerating = currentStage === "VISUAL_PLAN_GENERATING";
  const isVPSetup = currentStage === "VISUAL_PLAN_SETUP";
  const isFinalReview = FINAL_REVIEW_STAGES.has(currentStage);
  const isRenderStage = RENDER_STAGES.has(currentStage);
  const previewVideo = (preview as Record<string, unknown> | null)?.video;
  const previewVideoPath =
    previewVideo && typeof previewVideo === "object"
      ? (previewVideo as Record<string, unknown>).path
      : null;

  // Determine max width — wider for storyboard scene grid
  const maxWidth = isStoryboardWorkspace ? 1200 : 960;

  const showGoBack =
    Boolean(run) &&
    Boolean(STAGE_BACK_LABELS[currentStage]) &&
    !(currentStage === "SCRIPT_REVIEW" && project?.source_type !== "idea");

  // ---- render ----

  // Invalid project ID
  if (Number.isNaN(numericProjectId)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p style={{ color: "#b91c1c" }}>Invalid project ID.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>
          Back to projects
        </Link>
      </div>
    );
  }

  // Loading
  if (loading) {
    return (
      <div
        role="status"
        aria-label="Loading project"
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: 24,
          textAlign: "center",
          color: "#6b7280",
        }}
      >
        Loading project\u2026
      </div>
    );
  }

  // Error
  if (error) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <div
          role="alert"
          style={{
            padding: "12px 16px",
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 6,
            color: "#b91c1c",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
        <Link to="/runs" style={{ color: "#4285f4", fontSize: 13 }}>
          Back to projects
        </Link>
      </div>
    );
  }

  // No project
  if (!project) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p>Project not found.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>
          Back to projects
        </Link>
      </div>
    );
  }

  return (
    <div style={{ maxWidth, margin: "0 auto", padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <Link
          to="/runs"
          style={{ color: "#6b7280", fontSize: 12, textDecoration: "none" }}
        >
          \u2190 Projects
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 4px" }}>
          {project.title || "Untitled Project"}
        </h1>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          Source: {project.source_type} \u00b7 Status:{" "}
          {run ? run.status : project.status}
          {run ? ` \u00b7 Stage: ${currentStage}` : ""}
        </span>

        {/* Stop / Resume / Delete actions */}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {run && run.status === "running" && (
            <button
              type="button"
              onClick={() => setConfirmAction("stop")}
              disabled={stopping}
              style={{
                padding: "6px 14px",
                border: "1px solid #dc2626",
                borderRadius: 6,
                background: "#fff",
                color: "#dc2626",
                fontSize: 12,
                fontWeight: 600,
                cursor: stopping ? "not-allowed" : "pointer",
              }}
            >
              {stopping ? "Stopping\u2026" : "\u23f9 Stop"}
            </button>
          )}
          {run &&
            (run.status === "cancelled" ||
              run.status === "failed" ||
              run.status === "paused") && (
              <button
                type="button"
                onClick={() => setConfirmAction("resume")}
                disabled={resuming}
                style={{
                  padding: "6px 14px",
                  border: "1px solid #16a34a",
                  borderRadius: 6,
                  background: "#fff",
                  color: "#16a34a",
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: resuming ? "not-allowed" : "pointer",
                }}
              >
                {resuming ? "Resuming\u2026" : "\u25b6 Resume"}
              </button>
            )}
          <button
            type="button"
            onClick={() => setConfirmAction("delete")}
            disabled={deleting}
            style={{
              padding: "6px 14px",
              border: "1px solid #dc2626",
              borderRadius: 6,
              background: "#fff",
              color: "#dc2626",
              fontSize: 12,
              fontWeight: 600,
              cursor: deleting ? "not-allowed" : "pointer",
            }}
          >
            {deleting ? "Deleting\u2026" : "\ud83d\uddd1 Delete Project"}
          </button>
        </div>
      </div>

      {/* Pipeline stepper */}
      {run && (
        <div style={{ marginBottom: 24 }}>
          <PipelineStepper
            currentStage={currentStage}
            failed={isFailed}
            sourceType={project.source_type as "idea" | "markdown" | "url"}
          />
        </div>
      )}

      {/* No run state */}
      {!run && (
        <div
          data-testid="no-run"
          style={{
            textAlign: "center",
            padding: 32,
            background: "#f9fafb",
            borderRadius: 8,
            border: "1px dashed #d1d5db",
            color: "#6b7280",
            marginBottom: 24,
          }}
        >
          <p style={{ margin: "0 0 8px", fontWeight: 600 }}>No runs yet</p>
          <p style={{ margin: 0, fontSize: 13 }}>
            This project has no pipeline runs. Go back to create a new one.
          </p>
        </div>
      )}

      {/* ═══════════════ Script Workspace ═══════════════ */}
      {run && isScriptWorkspace && (
        <div style={{ marginBottom: 24 }}>
          <ScriptComposer
            runId={run.id}
            currentStage={currentStage}
            sourceType={project.source_type as "idea" | "markdown" | "url"}
            sourceContext={
              project.source_type === "idea"
                ? project.idea_brief
                : project.source_type === "markdown"
                  ? project.markdown_source
                  : project.url_source
            }
            selectedScriptModel={modelSelection.script_model}
            onModelChange={handleModelChange}
            onConfirm={handleApprove}
            onGenerate={handleGenerate}
            onRegenerate={handleRestart}
            onStatusMessage={setStatusMessage}
            disabled={approving || generating || restarting}
          />
        </div>
      )}

      {/* ═══════════════ Visual Plan Workspace ═══════════════ */}
      {run && isVisualPlanStage && (
        <div style={{ marginBottom: 24 }}>
          {(isVPSetup || isVPGenerating) && (
            <div
              data-testid="vp-generating-indicator"
              style={{
                padding: "10px 14px",
                background: "#f0fdf4",
                borderRadius: 8,
                border: "1px solid #bbf7d0",
                color: "#166534",
                marginBottom: 12,
                fontSize: 13,
              }}
            >
              {isVPGenerating
                ? "Generating Visual Plan\u2026 Scene prompts will appear here automatically."
                : "Visual plan not generated yet. Review the source mapping below, then generate it in place."}
            </div>
          )}
          <div
            style={{
              padding: "16px 20px",
              background: "linear-gradient(135deg, #eff6ff 0%, #f5f3ff 100%)",
              borderRadius: 10,
              border: "1px solid #c7d2fe",
              marginBottom: 16,
            }}
          >
            <h3
              style={{
                margin: "0 0 6px",
                fontSize: 16,
                fontWeight: 700,
                color: "#1e3a5f",
              }}
            >
              Visual Plan Setup
            </h3>
            <p
              style={{
                margin: 0,
                fontSize: 13,
                color: "#4b5563",
                lineHeight: 1.5,
              }}
            >
              Review the paragraph-to-image mapping below. Each paragraph in
              your script will generate one image. Select the script model that
              will draft the visual plan, then click
              <strong> Generate Visual Plan</strong> to proceed.
            </p>
          </div>

          {/* Script model selector for visual-plan drafting */}
          <div style={{ marginBottom: 16 }}>
            <ModelSelector
              categories={["script"]}
              selectedModels={buildSelectedModels(["script"])}
              apiBase=""
              onSelectionChange={handleModelChange}
            />
          </div>

          {/* Paragraph \u2192 Image cards */}
          <VisualPlanSetupCards runId={run.id} />
          <div style={{ marginTop: 16 }}>
            <VisualPlanEditor
              runId={run.id}
              readOnly={currentStage !== "VISUAL_PLAN_REVIEW"}
              pollIntervalMs={isVPSetup || isVPGenerating ? 3000 : undefined}
              suppressMissingPlanError={isVPSetup || isVPGenerating}
              pendingMessage={
                isVPSetup
                  ? "No visual plan yet. Generate it from the mapped script sections above."
                  : "Waiting for generated scenes\u2026"
              }
              onSuccess={() => setStatusMessage("Visual plan saved")}
              onError={(_action, msg) => setStatusMessage(msg)}
            />
          </div>

          {/* Visual plan action buttons */}
          <div
            style={{
              display: "flex",
              gap: 8,
              marginTop: 16,
              justifyContent: "flex-end",
            }}
          >
            {isVPSetup && (
              <button
                type="button"
                data-testid="generate-vp-btn"
                disabled={generating}
                onClick={handleGenerateVisualPlan}
                style={{
                  padding: "8px 20px",
                  border: "none",
                  borderRadius: 6,
                  background: generating ? "#9ca3af" : "#4285f4",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: generating ? "not-allowed" : "pointer",
                }}
              >
                {generating ? "Generating\u2026" : "Generate Visual Plan"}
              </button>
            )}
            {currentStage === "VISUAL_PLAN_REVIEW" && (
              <>
                <button
                  type="button"
                  data-testid="restart-vp-btn"
                  disabled={restarting}
                  onClick={handleRestartVisualPlan}
                  style={{
                    padding: "8px 20px",
                    border: "1px solid #d1d5db",
                    borderRadius: 6,
                    background: "#fff",
                    color: "#374151",
                    fontSize: 13,
                    fontWeight: 500,
                    cursor: restarting ? "not-allowed" : "pointer",
                  }}
                >
                  {restarting ? "Restarting\u2026" : "Regenerate Plan"}
                </button>
                <button
                  type="button"
                  data-testid="approve-vp-btn"
                  disabled={approving}
                  onClick={handleApproveVisualPlan}
                  style={{
                    padding: "8px 20px",
                    border: "none",
                    borderRadius: 6,
                    background: approving ? "#9ca3af" : "#16a34a",
                    color: "#fff",
                    fontSize: 13,
                    fontWeight: 600,
                    cursor: approving ? "not-allowed" : "pointer",
                  }}
                >
                  {approving ? "Approving\u2026" : "Approve Visual Plan"}
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {/* ═══════════════ Storyboard Workspace (Scene-Centric) ═══════════════ */}
      {run && isStoryboardWorkspace && (
        <div style={{ marginBottom: 24 }}>
          <StoryboardWorkspace
            runId={run.id}
            ttsModel={modelSelection.tts_model}
            subtitleModel={modelSelection.subtitle_model}
            imageModel={modelSelection.image_model}
            onStatusMessage={setStatusMessage}
            onRender={handleRender}
            rendering={generating}
          />

          {/* Final review extras — review link + video path */}
          {isFinalReview && (
            <div
              data-testid="final-review-section"
              style={{
                textAlign: "center",
                padding: 24,
                marginTop: 16,
                background: "#f0fdf4",
                borderRadius: 8,
                border: "1px solid #bbf7d0",
                color: "#166534",
              }}
            >
              <p
                style={{
                  margin: "0 0 8px",
                  fontWeight: 600,
                  fontSize: 16,
                }}
              >
                Pipeline Complete
              </p>
              <p style={{ margin: "0 0 16px", fontSize: 13 }}>
                All stages are done. Review the final output or restart from
                any stage.
              </p>
              {typeof previewVideoPath === "string" && (
                <p
                  style={{
                    margin: "0 0 8px",
                    fontSize: 13,
                    color: "#374151",
                  }}
                >
                  Video: {previewVideoPath}
                </p>
              )}
              <Link
                to={`/review/${run.id}`}
                data-testid="review-link"
                style={{
                  display: "inline-block",
                  padding: "8px 24px",
                  background: "#166534",
                  color: "#fff",
                  borderRadius: 6,
                  textDecoration: "none",
                  fontWeight: 600,
                  fontSize: 14,
                }}
              >
                Open Review Page \u2192
              </Link>
            </div>
          )}
        </div>
      )}

      {/* Back navigation button */}
      {showGoBack && (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-start",
            padding: "8px 0",
          }}
        >
          <button
            type="button"
            data-testid="go-back-btn"
            disabled={goingBack}
            onClick={handleGoBack}
            style={{
              padding: "6px 16px",
              fontSize: 13,
              fontWeight: 500,
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#fff",
              color: "#374151",
              cursor: goingBack ? "not-allowed" : "pointer",
              opacity: goingBack ? 0.6 : 1,
            }}
          >
            {goingBack
              ? "Going back\u2026"
              : STAGE_BACK_LABELS[currentStage]}
          </button>
        </div>
      )}

      {/* Status toast */}
      {statusMessage && (
        <div
          data-testid="status-toast"
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 24px",
            background: "#1f2937",
            color: "#fff",
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 500,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: 1000,
          }}
        >
          {statusMessage}
        </div>
      )}

      {/* Confirm dialog for stop / resume / delete */}
      <ConfirmDialog
        open={confirmAction !== null}
        title={
          confirmAction === "stop"
            ? "Stop Run?"
            : confirmAction === "resume"
              ? "Resume Run?"
              : "Delete Project?"
        }
        message={
          confirmAction === "stop"
            ? "This will cancel the current generation task and stop the pipeline run."
            : confirmAction === "resume"
              ? "This will resume the stopped/failed run from where it left off."
              : "This will permanently delete the project and all its runs, assets, and generated content. This action cannot be undone."
        }
        variant={
          confirmAction === "stop"
            ? "warning"
            : confirmAction === "resume"
              ? "info"
              : "danger"
        }
        confirmLabel={
          confirmAction === "stop"
            ? "Stop Run"
            : confirmAction === "resume"
              ? "Resume"
              : "Delete Forever"
        }
        loading={stopping || resuming || deleting}
        onConfirm={async () => {
          if (confirmAction === "stop") await handleStop();
          else if (confirmAction === "resume") await handleResume();
          else if (confirmAction === "delete") await handleDeleteProject();
          setConfirmAction(null);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
