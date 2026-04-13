import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import ProjectHeader from "./project/ProjectHeader";
import ScriptSection from "./project/ScriptSection";
import {
  API_BASE,
  FINAL_REVIEW_STAGES,
  STAGE_BACK_LABELS,
} from "./project/types";
import { useProjectData } from "./project/useProjectData";
import WorkspaceSection from "./project/WorkspaceSection";

type SourceType = "idea" | "markdown" | "json" | "pasted_json" | "url";

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();

  const {
    project,
    setProject,
    run,
    loading,
    error,
    preview,
    modelSelection,
    onModelChange,
    refreshRun,
  } = useProjectData(numericProjectId);

  const [approving, setApproving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const [stopping, setStopping] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [confirmAction, setConfirmAction] = useState<"stop" | "resume" | "delete" | null>(
    null,
  );

  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [scriptVersion, setScriptVersion] = useState(0);
  const [titleDraft, setTitleDraft] = useState("");
  const [savingTitle, setSavingTitle] = useState(false);
  const [goingBack, setGoingBack] = useState(false);

  const handleTitleSave = useCallback(async () => {
    const trimmed = titleDraft.trim();
    if (!trimmed || trimmed === project?.title) return;
    setSavingTitle(true);
    try {
      const res = await fetch(`${API_BASE}/projects/${numericProjectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Rename failed (${res.status})`);
      }
      const data = await res.json();
      setProject((prev) => (prev ? { ...prev, title: data.title } : prev));
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Rename failed");
    } finally {
      setSavingTitle(false);
    }
  }, [titleDraft, project?.title, numericProjectId, setProject]);

  useEffect(() => {
    if (project?.title && !titleDraft) {
      setTitleDraft(project.title);
    }
  }, [project?.title, titleDraft]);

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
      const restartRes = await fetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "SCRIPT_GENERATING" }),
      });
      if (!restartRes.ok) {
        const body = await restartRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${restartRes.status})`);
      }
      // Dispatch script generation task after stage reset
      const genRes = await fetch(`${API_BASE}/runs/${run.id}/generate-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!genRes.ok) {
        const body = await genRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${genRes.status})`);
      }
      setStatusMessage("Restarting script generation\u2026");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Restart failed");
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun, modelSelection.script_model]);

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
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
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
      const restartRes = await fetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "VISUAL_PLAN_GENERATING" }),
      });
      if (!restartRes.ok) {
        const body = await restartRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${restartRes.status})`);
      }
      // Dispatch visual plan generation task after stage reset
      const genRes = await fetch(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!genRes.ok) {
        const body = await genRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Generate failed (${genRes.status})`);
      }
      setStatusMessage("Restarting visual plan generation\u2026");
      setTimeout(() => refreshRun(run.id), 2000);
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Restart failed");
    } finally {
      setRestarting(false);
    }
  }, [run, refreshRun, modelSelection.script_model]);

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

  const currentStage = run?.current_stage ?? "IDEA_READY";
  const isFailed = run?.status === "failed";
  const showScriptComposer = true;
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
        Loading project…
      </div>
    );
  }

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

  void isFailed;

  return (
    <div style={{ maxWidth, margin: "0 auto", padding: 24 }}>
      <ProjectHeader
        project={project}
        run={run}
        titleDraft={titleDraft}
        setTitleDraft={setTitleDraft}
        savingTitle={savingTitle}
        onTitleSave={handleTitleSave}
        stopping={stopping}
        resuming={resuming}
        deleting={deleting}
        confirmAction={confirmAction}
        setConfirmAction={setConfirmAction}
        onStop={handleStop}
        onResume={handleResume}
        onDelete={handleDeleteProject}
        onNavigateBack={() => navigate("/runs")}
        currentStage={currentStage}
      />

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
        <ScriptSection
          runId={run.id}
          currentStage={currentStage}
          sourceType={project.source_type as SourceType}
          selectedScriptModel={modelSelection.script_model}
          onModelChange={onModelChange}
          onConfirm={handleApprove}
          onGenerate={handleGenerate}
          onRegenerate={handleRestart}
          onScriptChange={() => setScriptVersion((v) => v + 1)}
          onStatusMessage={(message) => setStatusMessage(message)}
          disabled={approving || generating || restarting}
        />
      )}

      {run && (
        <WorkspaceSection
          run={run}
          currentStage={currentStage}
          refreshTrigger={scriptVersion}
          modelSelection={modelSelection}
          onStatusMessage={(message) => setStatusMessage(message)}
          onRender={handleRender}
          rendering={generating}
          stageActionLoading={approving || generating || restarting}
          onGenerateVisualPlan={handleGenerateVisualPlan}
          onApproveVisualPlan={handleApproveVisualPlan}
          onRegenerateVisualPlan={handleRestartVisualPlan}
          isFinalReview={isFinalReview}
          previewVideoPath={typeof previewVideoPath === "string" ? previewVideoPath : null}
          showGoBack={showGoBack}
          onGoBack={handleGoBack}
          goingBack={goingBack}
          goBackLabel={STAGE_BACK_LABELS[currentStage]}
        />
      )}

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
    </div>
  );
}
