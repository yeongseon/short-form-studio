/**
 * ProjectPage — main working page for a short-form video project.
 *
 * Loads the project detail and its latest run, then renders:
 * - PipelineStepper (header progress bar)
 * - Editor area with markdown / structured toggle (during script stages)
 * - VisualPlanEditor (during visual plan stages)
 * - StageActionBar (save / approve / generate / restart)
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";

import PipelineStepper from "../components/creator/PipelineStepper";
import StageActionBar, {
  type ActionConfig,
} from "../components/creator/StageActionBar";
import MarkdownScriptEditor from "../components/creator/MarkdownScriptEditor";
import StructuredScriptEditor from "../components/creator/StructuredScriptEditor";
import VisualPlanEditor from "../components/creator/VisualPlanEditor";

const API_BASE = "/api/creator";

// --------------- types ---------------

interface ProjectDetail {
  id: number;
  title: string | null;
  source_type: string;
  status: string;
}

interface RunDetail {
  id: number;
  project_id: number;
  current_stage: string;
  status: string;
  restart_from: string | null;
}

type EditorMode = "markdown" | "structured";

// Script stages where the editor area is relevant
const SCRIPT_STAGES = new Set(["SCRIPT_GENERATING", "SCRIPT_REVIEW"]);

// Visual plan stages where the editor area is relevant
const VISUAL_PLAN_STAGES = new Set(["VISUAL_PLAN_GENERATING", "VISUAL_PLAN_REVIEW"]);

// Stages where editing is allowed (not generating)
const EDITABLE_STAGES = new Set(["SCRIPT_REVIEW", "VISUAL_PLAN_REVIEW"]);

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);

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

  // Status toast
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

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

  // ---- actions ----

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
        body: JSON.stringify({ model_key: "qwen3-4b" }),
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
  }, [run, refreshRun]);

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
        body: JSON.stringify({ model_key: "qwen3-4b" }),
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
  }, [run, refreshRun]);

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

  // ---- derived state ----

  const currentStage = run?.current_stage ?? "IDEA_READY";
  const isFailed = run?.status === "failed";
  const isScriptStage = SCRIPT_STAGES.has(currentStage);
  const isVisualPlanStage = VISUAL_PLAN_STAGES.has(currentStage);
  const isEditable = EDITABLE_STAGES.has(currentStage);
  const isGenerating = currentStage === "SCRIPT_GENERATING";
  const isVPGenerating = currentStage === "VISUAL_PLAN_GENERATING";
  // ---- action bar config ----

  const buildActionBar = (): {
    save: ActionConfig;
    approve: ActionConfig;
    generate: ActionConfig;
    restart: ActionConfig;
  } => {
    // Visual plan stages
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
        visible: currentStage === "IDEA_READY" || currentStage === "SCRIPT_REVIEW",
        disabled: generating,
        loading: generating,
        onClick: currentStage === "SCRIPT_REVIEW" ? handleGenerateVisualPlan : handleGenerate,
        label: currentStage === "SCRIPT_REVIEW" ? "Generate Visual Plan" : "Generate Script",
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
          Source: {project.source_type} · Status: {project.status}
        </span>
      </div>

      {/* Pipeline stepper */}
      {run && (
        <div style={{ marginBottom: 24 }}>
          <PipelineStepper currentStage={currentStage} failed={isFailed} />
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

      {/* Generating indicator */}
      {run && isGenerating && (
        <div
          data-testid="generating-indicator"
          style={{
            textAlign: "center",
            padding: 32,
            background: "#eff6ff",
            borderRadius: 8,
            border: "1px solid #bfdbfe",
            color: "#1e40af",
            marginBottom: 24,
          }}
        >
          <p style={{ margin: "0 0 4px", fontWeight: 600 }}>Generating Script…</p>
          <p style={{ margin: 0, fontSize: 13 }}>
            The AI model is writing your script. This may take a moment.
          </p>
        </div>
      )}

      {/* Visual plan generating indicator */}
      {run && isVPGenerating && (
        <div
          data-testid="vp-generating-indicator"
          style={{
            textAlign: "center",
            padding: 32,
            background: "#f0fdf4",
            borderRadius: 8,
            border: "1px solid #bbf7d0",
            color: "#166534",
            marginBottom: 24,
          }}
        >
          <p style={{ margin: "0 0 4px", fontWeight: 600 }}>Generating Visual Plan…</p>
          <p style={{ margin: 0, fontSize: 13 }}>
            The AI model is creating scene descriptions. This may take a moment.
          </p>
        </div>
      )}

      {/* Script editor area */}
      {run && isScriptStage && !isGenerating && (
        <div style={{ marginBottom: 24 }}>
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
                onSuccess={() => setStatusMessage("Script saved")}
                onError={(_action, msg) => setStatusMessage(msg)}
              />
            </div>
          )}
        </div>
      )}
      {/* Visual plan editor area */}
      {run && isVisualPlanStage && !isVPGenerating && (
        <div style={{ marginBottom: 24 }}>
          <VisualPlanEditor
            runId={run.id}
            readOnly={currentStage !== "VISUAL_PLAN_REVIEW"}
            onSuccess={() => setStatusMessage("Visual plan saved")}
            onError={(_action, msg) => setStatusMessage(msg)}
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
    </div>
  );
}
