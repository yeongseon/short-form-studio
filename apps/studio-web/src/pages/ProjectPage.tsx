/**
 * ProjectPage — main working page for a short-form video project.
 *
 * Loads the project detail and its latest run, then renders:
 * - PipelineStepper (header progress bar)
 * - Editor area with markdown / structured toggle (during script stages)
 * - VisualPlanEditor (during visual plan stages)
 * - VisualAssetGrid (during visual asset stages)
 * - Audio / subtitle / render generating indicators (automatic stages)
 * - Final review section with preview summary and review-page link
 * - StageActionBar (save / approve / generate / restart)
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";

import PipelineStepper from "../components/creator/PipelineStepper";
import StageActionBar, {
  type ActionConfig,
} from "../components/creator/StageActionBar";
import MarkdownScriptEditor from "../components/creator/MarkdownScriptEditor";
import StructuredScriptEditor from "../components/creator/StructuredScriptEditor";
import VisualPlanEditor from "../components/creator/VisualPlanEditor";
import VisualAssetGrid from "../components/creator/VisualAssetGrid";
import ModelSelector from "../components/creator/ModelSelector";
import StoryboardView from "../components/creator/StoryboardView";
import ConfirmDialog from "../components/creator/ConfirmDialog";

const API_BASE = "/api/creator";

// --------------- types ---------------

interface ProjectDetail {
  id: number;
  title: string | null;
  source_type: string;
  status: string;
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

// Script stages where the editor area is relevant
const SCRIPT_STAGES = new Set(["SCRIPT_GENERATING", "SCRIPT_REVIEW"]);

// Visual plan stages where the editor area is relevant
const VISUAL_PLAN_STAGES = new Set(["VISUAL_PLAN_SETUP", "VISUAL_PLAN_GENERATING", "VISUAL_PLAN_REVIEW"]);

// Visual asset stages
const VISUAL_ASSET_STAGES = new Set(["VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW"]);

// Audio stage
const AUDIO_STAGES = new Set(["AUDIO_GENERATING"]);

// Subtitle stage
const SUBTITLE_STAGES = new Set(["SUBTITLE_GENERATING"]);

// Render stage
const RENDER_STAGES = new Set(["RENDER_GENERATING"]);

// Final review
const FINAL_REVIEW_STAGES = new Set(["FINAL_REVIEW"]);

// Storyboard stages — show unified storyboard view instead of separate indicators
const STORYBOARD_STAGES = new Set(["AUDIO_GENERATING", "SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW"]);
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
  fast: { steps: 15, cfg_scale: 5, sampler_name: "Euler a", label: "⚡ Fast Preview", description: "Quick preview, lower quality (15 steps)" },
  balanced: { steps: 25, cfg_scale: 7, sampler_name: "DPM++ 2M Karras", label: "⚖️ Balanced", description: "Good quality/speed balance (25 steps)" },
  high: { steps: 40, cfg_scale: 8, sampler_name: "DPM++ 2M Karras", label: "✨ High Quality", description: "Best quality, slower (40 steps)" },
};

const SD_SAMPLERS = [
  "DPM++ 2M Karras", "DPM++ SDE Karras", "DPM++ 2M SDE Karras",
  "DPM++ 2M", "DPM++ SDE", "DPM++ 2S a Karras",
  "Euler a", "Euler", "DDIM", "UniPC", "LMS Karras", "Heun",
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
              background: sec.type === "narration" ? "#eff6ff" : sec.type === "dialogue" ? "#fdf4ff" : "#f0fdf4",
              borderRight: "1px solid #e5e7eb",
              padding: "12px 0",
              flexShrink: 0,
            }}
          >
            <span style={{ fontSize: 11, color: "#6b7280", fontWeight: 500 }}>\u00a7{idx + 1}</span>
            <span
              style={{
                fontSize: 10,
                color:
                  sec.type === "narration" ? "#2563eb" : sec.type === "dialogue" ? "#7c3aed" : "#16a34a",
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
              <span style={{ fontSize: 11, color: "#9ca3af", marginTop: 4, display: "inline-block" }}>
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
            <span style={{ fontSize: 20 }}>\ud83d\uddbc\ufe0f</span>
            <span style={{ fontSize: 10, color: "#6b21a8", fontWeight: 600, marginTop: 4 }}>1 Image</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();

  // Data state
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Editor mode
  const [editorMode, setEditorMode] = useState<EditorMode>("markdown");

  // Action loading states
  const [approving, setApproving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [restarting, setRestarting] = useState(false);

  // Stop / Resume / Delete states
  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"stop" | "resume" | "delete" | null>(null);

  // Status toast
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  // Scene regeneration model override
  const [regenModelKey, setRegenModelKey] = useState<string | null>(null);

  // SD image tuning parameters
  const [imageParams, setImageParams] = useState({
    steps: 25,
    sampler_name: "DPM++ 2M Karras",
    negative_prompt:
      "low quality, worst quality, blurry, out of focus, ugly, deformed, disfigured, watermark, text, signature, poorly drawn, bad anatomy, extra limbs",
    cfg_scale: 7,
  });
  const [activePreset, setActivePreset] = useState<string>("balanced");
  const [tuningOpen, setTuningOpen] = useState(true);
  // Asset grid refresh key — increment to force re-fetch
  const [assetRefreshKey, setAssetRefreshKey] = useState(0);

  // Preview data for FINAL_REVIEW
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);

  // Per-stage model selection (persisted to backend via model_defaults)
  const [modelSelection, setModelSelection] = useState<ModelDefaults>({});
  const [goingBack, setGoingBack] = useState(false);

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
        throw new Error(body?.detail ?? `Failed to load project (${projRes.status})`);
      }
      const projData: ProjectDetail = await projRes.json();
      setProject(projData);

      // 2. Fetch runs for this project (newest first), take the latest
      const runsRes = await fetch(`${API_BASE}/projects/${numericProjectId}/runs`);
      if (runsRes.ok) {
        const runsData: { runs: RunDetail[]; total: number } = await runsRes.json();
        setRun(runsData.runs.length > 0 ? runsData.runs[0] : null);
      } else {
        setRun(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
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
      if (run.current_stage === "VISUAL_ASSET_GENERATING") {
        setAssetRefreshKey((k) => k + 1);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [run, refreshRun]);

  // Initialize model selection from run.model_defaults on load
  useEffect(() => {
    if (run?.model_defaults) {
      setModelSelection((prev) => {
        // Only set if we don't have local selections yet
        const hasLocal = Object.keys(prev).length > 0;
        if (hasLocal) return prev;
        return { ...run.model_defaults } as ModelDefaults;
      });
    }
  }, [run?.model_defaults]);

  // Build a selectedModels map scoped to specific categories.
  // Returns undefined when none of the requested categories have persisted values,
  // so ModelSelector stays uncontrolled and can compute its own defaults.
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
        if (catSet.has(cat) && modelSelection[field as keyof ModelDefaults]) {
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
      // Map ModelSelector category → ModelDefaults field
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
      // Fire-and-forget persist to backend
      if (run) {
        fetch(`${API_BASE}/runs/${run.id}/model-defaults`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: modelKey }),
        }).catch(() => { /* non-critical */ });
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
        body: JSON.stringify({ model_key: modelSelection.script_model || "qwen3-4b" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${res.status})`);
      }
      setStatusMessage("Script generation started");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Generate failed");
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
      setStatusMessage("Restarting script generation…");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Restart failed");
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
      const res = await fetch(`${API_BASE}/runs/${run.id}/approve-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
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
      const res = await fetch(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_key: modelSelection.script_model || "qwen3-4b" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${res.status})`);
      }
      setStatusMessage("Visual plan generation started");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Generate failed");
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
      setStatusMessage("Restarting visual plan generation…");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Restart failed");
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun]);

  // ---- visual asset actions ----

  const handleGenerateAllAssets = useCallback(async () => {
    if (!run) return;
    setGenerating(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/generate-visual-assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_key: modelSelection.image_model || "sd15", image_params: imageParams }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate assets failed (${res.status})`);
      }
      setStatusMessage("Visual asset generation started");
      await refreshRun(run.id);
      setAssetRefreshKey((k) => k + 1);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Generate assets failed");
    } finally {
      setGenerating(false);
    }
  }, [run, imageParams, modelSelection.image_model]);

  const handleRegenerateScene = useCallback(
    async (sceneId: string) => {
      if (!run) return;
      setStatusMessage(null);
      try {
        const payload: Record<string, unknown> = { image_params: imageParams };
        if (regenModelKey) payload.model_key = regenModelKey;
        const res = await fetch(
          `${API_BASE}/runs/${run.id}/visual-plan/scenes/${sceneId}/regenerate-image`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          },
        );
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `Regenerate failed (${res.status})`);
        }
        setStatusMessage(`Regenerating scene ${sceneId}…`);
        // Refresh asset grid after a short delay for task to complete
        setTimeout(() => {
          setAssetRefreshKey((k) => k + 1);
          if (run) refreshRun(run.id);
        }, 3000);
      } catch (err) {
        setStatusMessage(err instanceof Error ? err.message : "Regenerate failed");
      }
    },
    [run, regenModelKey, imageParams, refreshRun],
  );

  const handleGenerateScene = useCallback(
    async (sceneId: string) => {
      if (!run) return;
      setStatusMessage(null);
      try {
        const res = await fetch(
          `${API_BASE}/runs/${run.id}/visual-plan/scenes/${sceneId}/generate-image`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_key: modelSelection.image_model || "sd15", image_params: imageParams }),
          },
        );
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `Generate scene failed (${res.status})`);
        }
        setStatusMessage(`Generating image for scene ${sceneId}…`);
        setTimeout(() => {
          setAssetRefreshKey((k) => k + 1);
          if (run) refreshRun(run.id);
        }, 3000);
      } catch (err) {
        setStatusMessage(err instanceof Error ? err.message : "Generate scene failed");
      }
    },
    [run, imageParams, refreshRun, modelSelection.image_model],
  );

  const handleApproveAssets = useCallback(async () => {
    if (!run) return;
    setApproving(true);
    setStatusMessage(null);
    try {
      const res = await fetch(`${API_BASE}/runs/${run.id}/approve-visual-assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Approve failed (${res.status})`);
      }
      setStatusMessage("Visual assets approved");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Approve assets failed");
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
      setStatusMessage("Restarting visual asset generation…");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Restart failed");
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
        body: JSON.stringify({ tts_model: modelSelection.tts_model || "qwen3-tts", voice: "default" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate audio failed (${res.status})`);
      }
      setStatusMessage("Audio generation started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Generate audio failed");
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
      const res = await fetch(`${API_BASE}/runs/${run.id}/generate-subtitles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subtitle_model: modelSelection.subtitle_model || "whisper-small", subtitle_format: "srt" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate subtitles failed (${res.status})`);
      }
      setStatusMessage("Subtitle generation started");
      await refreshRun(run.id);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Generate subtitles failed");
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
        body: JSON.stringify({ render_profile: modelSelection.render_profile || "shorts_default" }),
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
      const res = await fetch(`${API_BASE}/runs/${run.id}/stop`, { method: "POST" });
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
      const res = await fetch(`${API_BASE}/runs/${run.id}/resume`, { method: "POST" });
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
      const res = await fetch(`${API_BASE}/projects/${numericProjectId}`, { method: "DELETE" });
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
  const isVisualPlanStage = VISUAL_PLAN_STAGES.has(currentStage);
  const isVisualAssetStage = VISUAL_ASSET_STAGES.has(currentStage);
  const isEditable = EDITABLE_STAGES.has(currentStage);
  const isGenerating = currentStage === "SCRIPT_GENERATING";
  const isVPGenerating = currentStage === "VISUAL_PLAN_GENERATING";
  const isVPSetup = currentStage === "VISUAL_PLAN_SETUP";
  const isVAGenerating = currentStage === "VISUAL_ASSET_GENERATING";
  const isAudioStage = AUDIO_STAGES.has(currentStage);
  const isSubtitleStage = SUBTITLE_STAGES.has(currentStage);
  const isRenderStage = RENDER_STAGES.has(currentStage);
  const isFinalReview = FINAL_REVIEW_STAGES.has(currentStage);
  const isStoryboardStage = STORYBOARD_STAGES.has(currentStage);
  const previewVideo = (preview as Record<string, unknown> | null)?.video;
  const previewVideoPath =
    previewVideo && typeof previewVideo === "object"
      ? (previewVideo as Record<string, unknown>).path
      : null;


  // ---- action bar config ----

  const buildActionBar = (): {
    save: ActionConfig;
    approve: ActionConfig;
    generate: ActionConfig;
    restart: ActionConfig;
  } => {
    // Final review — no actions needed, just view
    if (isFinalReview) {
      return {
        save: { visible: false },
        approve: { visible: false },
        generate: { visible: false },
        restart: {
          visible: true,
          disabled: restarting,
          loading: restarting,
          onClick: handleRestart,
          label: "Restart from Script",
        },
      };
    }

    // Storyboard stages — audio/subtitle generation is handled by StoryboardView
    // Only show render button and restart in the action bar
    if (isAudioStage) {
      return {
        save: { visible: false },
        approve: { visible: false },
        generate: { visible: false },
        restart: {
          visible: true,
          disabled: restarting,
          loading: restarting,
          onClick: handleRestart,
          label: "Restart from Script",
        },
      };
    }

    if (isSubtitleStage) {
      return {
        save: { visible: false },
        approve: { visible: false },
        generate: {
          visible: true,
          disabled: generating,
          loading: generating,
          onClick: handleRender,
          label: "Render Video",
        },
        restart: {
          visible: true,
          disabled: restarting,
          loading: restarting,
          onClick: handleRestart,
          label: "Restart from Script",
        },
      };
    }

    // Render stage — rendering in progress, show restart only
    if (isRenderStage) {
      return {
        save: { visible: false },
        approve: { visible: false },
        generate: { visible: false },
        restart: {
          visible: true,
          disabled: restarting,
          loading: restarting,
          onClick: handleRestart,
          label: "Restart from Script",
        },
      };
    }

    // Visual asset stages
    if (isVisualAssetStage) {
      return {
        save: { visible: false },
        approve: {
          visible: currentStage === "VISUAL_ASSET_REVIEW",
          disabled: approving,
          loading: approving,
          onClick: handleApproveAssets,
          label: "Approve Assets",
        },
        generate: {
          visible: currentStage === "VISUAL_ASSET_REVIEW",
          disabled: generating,
          loading: generating,
          onClick: handleGenerateAllAssets,
          label: "Regenerate All",
        },
        restart: {
          visible: currentStage === "VISUAL_ASSET_REVIEW",
          disabled: restarting,
          loading: restarting,
          onClick: handleRestartAssets,
          label: "Restart Assets",
        },
      };
    }

    // Visual plan stages
    // Visual plan setup — show only "Generate Visual Plan" button
    if (isVPSetup) {
      return {
        save: { visible: false },
        approve: { visible: false },
        generate: {
          visible: true,
          disabled: generating,
          loading: generating,
          onClick: handleGenerateVisualPlan,
          label: "Generate Visual Plan",
        },
        restart: { visible: false },
      };
    }

    if (isVisualPlanStage) {
      return {
        save: { visible: false },
        approve: {
          visible: currentStage === "VISUAL_PLAN_REVIEW",
          disabled: approving,
          loading: approving,
          onClick: handleApproveVisualPlan,
          label: "Approve Visual Plan",
        },
        generate: { visible: false },
        restart: {
          visible: currentStage === "VISUAL_PLAN_REVIEW",
          disabled: restarting,
          loading: restarting,
          onClick: handleRestartVisualPlan,
          label: "Regenerate Plan",
        },
      };
    }

    // Script stages and transitions
    return {
      save: { visible: false },
      approve: {
        visible: currentStage === "SCRIPT_REVIEW",
        disabled: approving,
        loading: approving,
        onClick: handleApprove,
        label: "Approve Script",
      },
      generate: {
        visible: currentStage === "IDEA_READY",
        disabled: generating,
        loading: generating,
        onClick: handleGenerate,
        label: "Generate Script",
      },
      restart: {
        visible: currentStage === "SCRIPT_REVIEW",
        disabled: restarting,
        loading: restarting,
        onClick: handleRestart,
        label: "Regenerate Script",
      },
    };
  };

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
        style={{ maxWidth: 720, margin: "0 auto", padding: 24, textAlign: "center", color: "#6b7280" }}
      >
        Loading project…
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

  const actions = buildActionBar();
  const showGoBack =
    Boolean(run) &&
    Boolean(STAGE_BACK_LABELS[currentStage]) &&
    !(currentStage === "SCRIPT_REVIEW" && project.source_type !== "idea");

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <Link to="/runs" style={{ color: "#6b7280", fontSize: 12, textDecoration: "none" }}>
          ← Projects
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 4px" }}>
          {project.title || "Untitled Project"}
        </h1>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          Source: {project.source_type} · Status: {run ? run.status : project.status}
          {run ? ` · Stage: ${currentStage}` : ""}
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
              {stopping ? "Stopping…" : "⏹ Stop"}
            </button>
          )}
          {run && (run.status === "cancelled" || run.status === "failed" || run.status === "paused") && (
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
              {resuming ? "Resuming…" : "▶ Resume"}
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
            {deleting ? "Deleting…" : "🗑 Delete Project"}
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

      {/* Script editor area */}
      {run && isScriptStage && (
        <div style={{ marginBottom: 24 }}>
          {isGenerating && (
            <div
              data-testid="generating-indicator"
              style={{
                padding: "10px 14px",
                background: "#eff6ff",
                borderRadius: 8,
                border: "1px solid #bfdbfe",
                color: "#1e40af",
                marginBottom: 12,
                fontSize: 13,
              }}
            >
              Generating Script… Current draft will update automatically.
            </div>
          )}
          {/* Editor mode toggle */}
          <div
            role="tablist"
            style={{
              display: "flex",
              gap: 4,
              marginBottom: 12,
              borderBottom: "2px solid #ddd",
            }}
          >
            <button
              type="button"
              role="tab"
              id="tab-markdown"
              aria-selected={editorMode === "markdown"}
              aria-controls="panel-markdown"
              onClick={() => setEditorMode("markdown")}
              style={{
                padding: "6px 14px",
                border: "none",
                borderBottom: editorMode === "markdown" ? "2px solid #4285f4" : "2px solid transparent",
                background: "transparent",
                cursor: "pointer",
                fontWeight: editorMode === "markdown" ? 600 : 400,
                color: editorMode === "markdown" ? "#4285f4" : "#666",
                fontSize: 13,
              }}
            >
              Markdown
            </button>
            <button
              type="button"
              role="tab"
              id="tab-structured"
              aria-selected={editorMode === "structured"}
              aria-controls="panel-structured"
              onClick={() => setEditorMode("structured")}
              style={{
                padding: "6px 14px",
                border: "none",
                borderBottom: editorMode === "structured" ? "2px solid #4285f4" : "2px solid transparent",
                background: "transparent",
                cursor: "pointer",
                fontWeight: editorMode === "structured" ? 600 : 400,
                color: editorMode === "structured" ? "#4285f4" : "#666",
                fontSize: 13,
              }}
            >
              Structured
            </button>
          </div>

          {/* Markdown editor panel */}
          {editorMode === "markdown" && (
            <div role="tabpanel" id="panel-markdown" aria-labelledby="tab-markdown">
              <MarkdownScriptEditor
                runId={run.id}
                readOnly={!isEditable}
                pollIntervalMs={isGenerating ? 3000 : undefined}
                suppressMissingDraftError={isGenerating}
                onSuccess={() => setStatusMessage("Script saved")}
                onError={(_action, msg) => setStatusMessage(msg)}
              />
            </div>
          )}

          {/* Structured editor panel */}
          {editorMode === "structured" && (
            <div role="tabpanel" id="panel-structured" aria-labelledby="tab-structured">
              <StructuredScriptEditor
                runId={run.id}
                readOnly={!isEditable}
                pollIntervalMs={isGenerating ? 3000 : undefined}
                suppressMissingDraftError={isGenerating}
                onSuccess={() => setStatusMessage("Script saved")}
                onError={(_action, msg) => setStatusMessage(msg)}
              />
            </div>
          )}
        </div>
      )}

      {/* Visual plan setup — paragraph→image mapping before generation */}
      {run && (isVPSetup || (isVPGenerating && !run.restart_from)) && (
        <div style={{ marginBottom: 24 }}>
          {isVPGenerating && (
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
              Generating Visual Plan… Scene prompts will appear here automatically.
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
            <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "#1e3a5f" }}>
              Visual Plan Setup
            </h3>
            <p style={{ margin: 0, fontSize: 13, color: "#4b5563", lineHeight: 1.5 }}>
              Review the paragraph-to-image mapping below. Each paragraph in your script will
              generate one image. Select the script model that will draft the visual plan, then click
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

          {/* Paragraph → Image cards */}
          <VisualPlanSetupCards runId={run.id} />
        </div>
      )}

      {/* Visual plan editor area */}
      {run && isVisualPlanStage && !(isVPSetup || (isVPGenerating && !run.restart_from)) && (
        <div style={{ marginBottom: 24 }}>
          {isVPGenerating && (
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
              Regenerating Visual Plan… Existing prompts stay visible until the new plan is ready.
            </div>
          )}
          <VisualPlanEditor
            runId={run.id}
            readOnly={currentStage !== "VISUAL_PLAN_REVIEW"}
            pollIntervalMs={isVPGenerating ? 3000 : undefined}
            suppressMissingPlanError={isVPGenerating}
            onSuccess={() => setStatusMessage("Visual plan saved")}
            onError={(_action, msg) => setStatusMessage(msg)}
          />
        </div>
      )}

      {/* Visual asset area */}
      {run && isVisualAssetStage && (
        <div data-testid="visual-asset-section" style={{ marginBottom: 24 }}>
          {/* Asset generating indicator */}
          {isVAGenerating && (
            <div
              data-testid="va-generating-indicator"
              style={{
                textAlign: "center",
                padding: 32,
                background: "#fdf4ff",
                borderRadius: 8,
                border: "1px solid #e9d5ff",
                color: "#6b21a8",
                marginBottom: 16,
              }}
            >
              <p style={{ margin: "0 0 4px", fontWeight: 600 }}>Generating Visual Assets…</p>
              <p style={{ margin: 0, fontSize: 13 }}>
                Image generation is in progress. This may take several minutes.
              </p>
            </div>
          )}

          {/* Asset grid — visible in review or generating (read-only during generation) */}
          <VisualAssetGrid
            key={assetRefreshKey}
            runId={run.id}
            apiBase={API_BASE}
            readOnly={isVAGenerating}
            onSelect={() => setStatusMessage("Active asset updated")}
            onError={(_action, msg) => setStatusMessage(msg)}
          />

          {/* Scene-level regeneration controls (review stage only) */}
          {currentStage === "VISUAL_ASSET_REVIEW" && (
            <div
              data-testid="scene-regen-controls"
              style={{
                marginTop: 16,
                padding: 16,
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                background: "#f9fafb",
              }}
            >
              <h4 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 600 }}>
                Regenerate Single Scene
              </h4>

              {/* Model override selector — image category only */}
              <div style={{ marginBottom: 12 }}>
                <ModelSelector
                  categories={["image"]}
                  apiBase={API_BASE}
                  onSelectionChange={(_cat, modelKey) => setRegenModelKey(modelKey)}
                />
              </div>

              {/* Image quality tuning controls */}
              <div
                data-testid="image-tuning-panel"
                style={{
                  marginBottom: 16,
                  border: "1px solid #e5e7eb",
                  borderRadius: 8,
                  background: "#fff",
                  overflow: "hidden",
                }}
              >
                {/* Panel header — toggle */}
                <button
                  type="button"
                  data-testid="tuning-toggle"
                  onClick={() => setTuningOpen((v) => !v)}
                  style={{
                    width: "100%",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "10px 14px",
                    background: "#faf5ff",
                    border: "none",
                    borderBottom: tuningOpen ? "1px solid #e5e7eb" : "none",
                    cursor: "pointer",
                    fontSize: 13,
                    fontWeight: 600,
                    color: "#6b21a8",
                  }}
                >
                  <span>🎨 Image Quality Settings</span>
                  <span style={{ fontSize: 11 }}>{tuningOpen ? "▲" : "▼"}</span>
                </button>

                {tuningOpen && (
                  <div style={{ padding: 14, display: "flex", flexDirection: "column", gap: 14 }}>
                    {/* Quality presets */}
                    <div>
                      <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 6 }}>
                        Quality Preset
                      </label>
                      <div style={{ display: "flex", gap: 6 }}>
                        {Object.entries(SD_QUALITY_PRESETS).map(([key, preset]) => (
                          <button
                            type="button"
                            key={key}
                            data-testid={`preset-${key}`}
                            title={preset.description}
                            onClick={() => {
                              setActivePreset(key);
                              setImageParams((p) => ({
                                ...p,
                                steps: preset.steps,
                                cfg_scale: preset.cfg_scale,
                                sampler_name: preset.sampler_name,
                              }));
                            }}
                            style={{
                              flex: 1,
                              padding: "6px 8px",
                              fontSize: 12,
                              fontWeight: activePreset === key ? 600 : 400,
                              border: activePreset === key ? "2px solid #7c3aed" : "1px solid #d1d5db",
                              borderRadius: 6,
                              background: activePreset === key ? "#ede9fe" : "#fff",
                              color: activePreset === key ? "#6b21a8" : "#374151",
                              cursor: "pointer",
                              transition: "all 0.15s",
                            }}
                          >
                            {preset.label}
                          </button>
                        ))}
                      </div>
                      <p style={{ margin: "4px 0 0", fontSize: 11, color: "#9ca3af" }}>
                        {SD_QUALITY_PRESETS[activePreset]?.description}
                      </p>
                    </div>

                    {/* Steps slider */}
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>
                          Steps
                        </label>
                        <span style={{ fontSize: 12, color: "#6b21a8", fontWeight: 600 }}>{imageParams.steps}</span>
                      </div>
                      <input
                        data-testid="steps-slider"
                        type="range"
                        min={15}
                        max={50}
                        value={imageParams.steps}
                        onChange={(e) => {
                          setActivePreset("");
                          setImageParams((p) => ({ ...p, steps: Number(e.target.value) }));
                        }}
                        style={{ width: "100%", accentColor: "#7c3aed" }}
                      />
                      <p style={{ margin: "2px 0 0", fontSize: 11, color: "#9ca3af" }}>
                        More steps = higher quality but slower. 20-30 is usually optimal.
                      </p>
                    </div>

                    {/* CFG Scale slider */}
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                        <label style={{ fontSize: 12, fontWeight: 600, color: "#374151" }}>
                          CFG Scale (Prompt Adherence)
                        </label>
                        <span style={{ fontSize: 12, color: "#6b21a8", fontWeight: 600 }}>{imageParams.cfg_scale}</span>
                      </div>
                      <input
                        data-testid="cfg-slider"
                        type="range"
                        min={1}
                        max={20}
                        value={imageParams.cfg_scale}
                        onChange={(e) => {
                          setActivePreset("");
                          setImageParams((p) => ({ ...p, cfg_scale: Number(e.target.value) }));
                        }}
                        style={{ width: "100%", accentColor: "#7c3aed" }}
                      />
                      <p style={{ margin: "2px 0 0", fontSize: 11, color: "#9ca3af" }}>
                        How closely to follow the prompt. 5-9 works well; too high can look harsh.
                      </p>
                    </div>

                    {/* Sampler dropdown */}
                    <div>
                      <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 4 }}>
                        Sampler
                      </label>
                      <select
                        data-testid="sampler-select"
                        value={imageParams.sampler_name}
                        onChange={(e) => {
                          setActivePreset("");
                          setImageParams((p) => ({ ...p, sampler_name: e.target.value }));
                        }}
                        style={{
                          width: "100%",
                          padding: "6px 10px",
                          border: "1px solid #d1d5db",
                          borderRadius: 4,
                          fontSize: 13,
                          background: "#fff",
                          color: "#374151",
                        }}
                      >
                        {SD_SAMPLERS.map((s) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                      <p style={{ margin: "2px 0 0", fontSize: 11, color: "#9ca3af" }}>
                        DPM++ 2M Karras gives best quality for SD 1.5. Euler a is fastest.
                      </p>
                    </div>

                    {/* Negative prompt */}
                    <div>
                      <label style={{ display: "block", fontSize: 12, fontWeight: 600, color: "#374151", marginBottom: 4 }}>
                        Negative Prompt
                      </label>
                      <textarea
                        data-testid="negative-prompt"
                        rows={3}
                        value={imageParams.negative_prompt}
                        onChange={(e) => {
                          setActivePreset("");
                          setImageParams((p) => ({ ...p, negative_prompt: e.target.value }));
                        }}
                        style={{
                          width: "100%",
                          padding: "6px 10px",
                          border: "1px solid #d1d5db",
                          borderRadius: 4,
                          fontSize: 12,
                          fontFamily: "inherit",
                          resize: "vertical",
                          color: "#374151",
                          boxSizing: "border-box",
                        }}
                      />
                      <p style={{ margin: "2px 0 0", fontSize: 11, color: "#9ca3af" }}>
                        Describe what you do NOT want in the image. Helps avoid common SD artifacts.
                      </p>
                    </div>
                  </div>
                )}
              </div>

              {/* Scene action buttons — rendered per-scene from the asset grid data is impractical
                  without lifting scene IDs up. Instead, provide a text input for scene ID. */}
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <input
                  data-testid="scene-id-input"
                  type="text"
                  placeholder="Scene ID (e.g. scene-0)"
                  style={{
                    flex: 1,
                    padding: "6px 10px",
                    border: "1px solid #d1d5db",
                    borderRadius: 4,
                    fontSize: 13,
                  }}
                  id="regen-scene-id"
                />
                <button
                  type="button"
                  data-testid="regen-scene-btn"
                  onClick={() => {
                    const input = document.getElementById("regen-scene-id") as HTMLInputElement;
                    const sceneId = input?.value?.trim();
                    if (sceneId) handleRegenerateScene(sceneId);
                  }}
                  style={{
                    padding: "6px 16px",
                    border: "1px solid #d1d5db",
                    borderRadius: 4,
                    background: "#fff",
                    cursor: "pointer",
                    fontSize: 13,
                  }}
                >
                  Regenerate
                </button>
                <button
                  type="button"
                  data-testid="generate-scene-btn"
                  onClick={() => {
                    const input = document.getElementById("regen-scene-id") as HTMLInputElement;
                    const sceneId = input?.value?.trim();
                    if (sceneId) handleGenerateScene(sceneId);
                  }}
                  style={{
                    padding: "6px 16px",
                    border: "1px solid #d1d5db",
                    borderRadius: 4,
                    background: "#fff",
                    cursor: "pointer",
                    fontSize: 13,
                  }}
                >
                  Generate New
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Unified Storyboard view — replaces separate audio/subtitle/render indicators */}
      {run && isStoryboardStage && (
        <div style={{ marginBottom: 24 }}>
          {!isRenderStage && (
            <div style={{ marginBottom: 12 }}>
              <ModelSelector
                categories={["tts", "stt"]}
                selectedModels={buildSelectedModels(["tts", "stt"])}
                apiBase=""
                onSelectionChange={handleModelChange}
              />
              <div style={{ marginTop: 12 }}>
                <label
                  htmlFor="project-render-profile"
                  style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}
                >
                  Render Profile
                </label>
                <select
                  id="project-render-profile"
                  value={modelSelection.render_profile || "shorts_default"}
                  onChange={(e) => handleModelChange("render", e.target.value)}
                  style={{ padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14 }}
                >
                  {RENDER_PROFILE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          )}
          <StoryboardView
            runId={run.id}
            readOnly={isRenderStage}
            currentStage={currentStage}
            onStatusMessage={setStatusMessage}
            onRenderReady={() => {
              if (run) refreshRun(run.id);
            }}
            ttsModel={modelSelection.tts_model}
            subtitleModel={modelSelection.subtitle_model}
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
              <p style={{ margin: "0 0 8px", fontWeight: 600, fontSize: 16 }}>
                Pipeline Complete
              </p>
              <p style={{ margin: "0 0 16px", fontSize: 13 }}>
                All stages are done. Review the final output or restart from any stage.
              </p>
              {typeof previewVideoPath === "string" && (
                <p style={{ margin: "0 0 8px", fontSize: 13, color: "#374151" }}>
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
                Open Review Page →
              </Link>
            </div>
          )}
        </div>
      )}

      {/* Back navigation button */}
      {showGoBack && (
        <div style={{ display: "flex", justifyContent: "flex-start", padding: "8px 16px" }}>
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
            {goingBack ? "Going back\u2026" : STAGE_BACK_LABELS[currentStage]}
          </button>
        </div>
      )}

      {/* Per-stage model selector */}
      {run && currentStage === "IDEA_READY" && (
        <div style={{ padding: "8px 16px" }}>
          <ModelSelector
            categories={["script"]}
            selectedModels={buildSelectedModels(["script"])}
            apiBase=""
            onSelectionChange={handleModelChange}
          />
        </div>
      )}
      {run && currentStage === "SCRIPT_REVIEW" && (
        <div style={{ padding: "8px 16px" }}>
          <ModelSelector
            categories={["script"]}
            selectedModels={buildSelectedModels(["script"])}
            apiBase=""
            onSelectionChange={handleModelChange}
          />
        </div>
      )}
      {run && currentStage === "VISUAL_PLAN_REVIEW" && (
        <div style={{ padding: "8px 16px" }}>
          <ModelSelector
            categories={["script"]}
            selectedModels={buildSelectedModels(["script"])}
            apiBase=""
            onSelectionChange={handleModelChange}
          />
        </div>
      )}
      {run && currentStage === "VISUAL_ASSET_REVIEW" && (
        <div style={{ padding: "8px 16px" }}>
          <ModelSelector
            categories={["image"]}
            selectedModels={buildSelectedModels(["image"])}
            apiBase=""
            onSelectionChange={handleModelChange}
          />
        </div>
      )}

      {/* Stage action bar */}
      {run && (
        <StageActionBar
          save={actions.save}
          approve={actions.approve}
          generate={actions.generate}
          restart={actions.restart}
          statusMessage={statusMessage ?? undefined}
        />
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
        variant={confirmAction === "stop" ? "warning" : confirmAction === "resume" ? "info" : "danger"}
        confirmLabel={confirmAction === "stop" ? "Stop Run" : confirmAction === "resume" ? "Resume" : "Delete Forever"}
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
