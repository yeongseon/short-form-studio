import { useCallback, useEffect, useState } from "react";

import { apiFetch } from "../../api/client";
import { API_BASE, type ModelDefaults, type ProjectDetail, type RunDetail } from "./types";

interface UseRunActionsParams {
  run: RunDetail | null;
  project: ProjectDetail | null;
  numericProjectId: number;
  modelSelection: ModelDefaults;
  setProject: React.Dispatch<React.SetStateAction<ProjectDetail | null>>;
  refreshRun: (runId: number) => Promise<void>;
  navigate: (path: string) => void;
}

export function useRunActions({
  run,
  project,
  numericProjectId,
  modelSelection,
  setProject,
  refreshRun,
  navigate,
}: UseRunActionsParams) {
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
      const res = await apiFetch(`${API_BASE}/projects/${numericProjectId}`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/go-back`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/approve-script`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/generate-script`, {
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
      const restartRes = await apiFetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "SCRIPT_GENERATING" }),
      });
      if (!restartRes.ok) {
        const body = await restartRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${restartRes.status})`);
      }
      // Dispatch script generation task after stage reset
      const genRes = await apiFetch(`${API_BASE}/runs/${run.id}/generate-script`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/approve-visual-plan`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
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
      const restartRes = await apiFetch(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "VISUAL_PLAN_GENERATING" }),
      });
      if (!restartRes.ok) {
        const body = await restartRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Restart failed (${restartRes.status})`);
      }
      // Dispatch visual plan generation task after stage reset
      const genRes = await apiFetch(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/render`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/stop`, {
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
      const res = await apiFetch(`${API_BASE}/runs/${run.id}/resume`, {
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
      const res = await apiFetch(`${API_BASE}/projects/${numericProjectId}`, {
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

  return {
    // Handlers
    handleTitleSave,
    handleGoBack,
    handleApprove,
    handleGenerate,
    handleRestart,
    handleApproveVisualPlan,
    handleGenerateVisualPlan,
    handleRestartVisualPlan,
    handleRender,
    handleStop,
    handleResume,
    handleDeleteProject,
    // Loading states
    approving,
    generating,
    restarting,
    stopping,
    resuming,
    deleting,
    savingTitle,
    goingBack,
    // UI states
    statusMessage,
    setStatusMessage,
    confirmAction,
    setConfirmAction,
    titleDraft,
    setTitleDraft,
    scriptVersion,
    setScriptVersion,
  };
}
