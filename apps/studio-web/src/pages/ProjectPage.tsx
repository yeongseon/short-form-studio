/**
 * ProjectPage — main working page for a short-form video project.
 *
 * Loads the project detail and its latest run, then renders:
 * - PipelineStepper (header progress bar)
 * - ScriptComposer (during script stages: IDEA_READY, SCRIPT_GENERATING, SCRIPT_REVIEW)
 * - UnifiedSceneWorkspace (single scene-centric grid view)
 * - Final review section with preview summary and review-page link
 * - ConfirmDialog for stop / resume / delete
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";

import PipelineStepper from "../components/creator/PipelineStepper";
import ScriptComposer from "../components/creator/ScriptComposer";
import UnifiedSceneWorkspace from "../components/creator/UnifiedSceneWorkspace";
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

// Final review
const FINAL_REVIEW_STAGES = new Set(["FINAL_REVIEW"]);

// Stages where we poll run status
const RUN_POLL_STAGES = new Set([
  "SCRIPT_GENERATING",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_ASSET_GENERATING",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
]);

// Back navigation labels per review stage
const STAGE_BACK_LABELS: Record<string, string> = {
  SCRIPT_REVIEW: "\u2190 Back to Idea",
  VISUAL_PLAN_SETUP: "\u2190 Back to Script Review",
  VISUAL_PLAN_REVIEW: "\u2190 Back to Visual Plan Setup",
  VISUAL_ASSET_REVIEW: "\u2190 Back to Visual Plan",
  FINAL_REVIEW: "\u2190 Back to Visual Assets",
};

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
  }, [run, modelSelection.render_profile, refreshRun]);

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
  const showScriptComposer = true; // Always show markdown editor when run exists
  const isFinalReview = FINAL_REVIEW_STAGES.has(currentStage);
  const previewVideo = (preview as Record<string, unknown> | null)?.video;
  const previewVideoPath =
    previewVideo && typeof previewVideo === "object"
      ? (previewVideo as Record<string, unknown>).path
      : null;

  const maxWidth = run ? 1200 : 960;

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

      {run && showScriptComposer && (
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

      {run && (
        <div style={{ marginBottom: 24 }}>
          <UnifiedSceneWorkspace
            runId={run.id}
            currentStage={currentStage}
            ttsModel={modelSelection.tts_model}
            subtitleModel={modelSelection.subtitle_model}
            imageModel={modelSelection.image_model}
            onStatusMessage={setStatusMessage}
            onRender={handleRender}
            rendering={generating}
            stageActionLoading={approving || generating || restarting}
            onGenerateVisualPlan={handleGenerateVisualPlan}
            onApproveVisualPlan={handleApproveVisualPlan}
            onRegenerateVisualPlan={handleRestartVisualPlan}
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
