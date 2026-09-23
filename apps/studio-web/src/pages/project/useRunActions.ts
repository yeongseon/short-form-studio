import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { apiJson, apiVoid } from "../../api/client";
import { API_BASE, type ModelDefaults, type ProjectDetail, type RunDetail } from "./types";
import { useToast } from "../../contexts/ToastContext";

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

  const { showToast, toast } = useToast();
  const [scriptVersion, setScriptVersion] = useState(0);
  const [titleDraft, setTitleDraft] = useState("");
  const titleOwner = useRef<number | null>(null);
  const activeProjectId = useRef(numericProjectId);
  const activeRunId = useRef(run?.id);
  const mounted = useRef(true);
  const actionOwner = useRef({ projectId: numericProjectId, runId: run?.id });
  const ownerSequence = useRef(0);
  const refreshTimers = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());
  const [savingTitle, setSavingTitle] = useState(false);
  const [goingBack, setGoingBack] = useState(false);

  activeProjectId.current = numericProjectId;
  activeRunId.current = run?.id;
  const ownsRun = useCallback((projectId: number, runId: number, sequence: number) =>
    mounted.current && activeProjectId.current === projectId &&
    activeRunId.current === runId && ownerSequence.current === sequence, []);

  useLayoutEffect(() => {
    if (actionOwner.current.projectId !== numericProjectId || actionOwner.current.runId !== run?.id) {
      actionOwner.current = { projectId: numericProjectId, runId: run?.id };
      ownerSequence.current += 1;
      setApproving(false);
      setGenerating(false);
      setRestarting(false);
      setStopping(false);
      setResuming(false);
      setGoingBack(false);
      setDeleting(false);
      setConfirmAction(null);
    }
  }, [numericProjectId, run?.id]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      activeProjectId.current = -1;
      activeRunId.current = undefined;
    };
  }, []);

  useEffect(() => () => {
    for (const timer of refreshTimers.current) clearTimeout(timer);
    refreshTimers.current.clear();
  }, [numericProjectId]);

  const scheduleRefresh = useCallback((runId: number, sequence: number) => {
    const owner = numericProjectId;
    const timer = setTimeout(() => {
      refreshTimers.current.delete(timer);
      if (ownsRun(owner, runId, sequence)) void refreshRun(runId);
    }, 2000);
    refreshTimers.current.add(timer);
  }, [numericProjectId, ownsRun, refreshRun]);

  const handleTitleSave = useCallback(async () => {
    const trimmed = titleDraft.trim();
    if (!trimmed || trimmed === project?.title) return;
    const sequence = ownerSequence.current;
    setSavingTitle(true);
    try {
      const data = await apiJson<{ title: string }>(`${API_BASE}/projects/${numericProjectId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      });
      if (mounted.current && activeProjectId.current === numericProjectId && ownerSequence.current === sequence) {
        setProject((prev) => (prev?.id === numericProjectId ? { ...prev, title: data.title } : prev));
      }
    } catch (err) {
      if (mounted.current && activeProjectId.current === numericProjectId && ownerSequence.current === sequence) {
        showToast(err instanceof Error ? err.message : "Rename failed", "error");
      }
    } finally {
      if (mounted.current && activeProjectId.current === numericProjectId && ownerSequence.current === sequence) setSavingTitle(false);
    }
   }, [titleDraft, project?.title, numericProjectId, setProject, showToast]);

  useEffect(() => {
    if (project && titleOwner.current !== project.id) {
      titleOwner.current = project.id;
      setTitleDraft(project.title ?? "");
      setSavingTitle(false);
    }
  }, [project]);

  const handleGoBack = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    const isCurrent = () => ownsRun(owner, runId, sequence);
    setGoingBack(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/go-back`, { method: "POST" });
      if (!isCurrent()) return;
      showToast("Navigated back");
      await refreshRun(run.id);
    } catch (err) {
      if (isCurrent()) showToast(err instanceof Error ? err.message : "Go back failed", "error");
    } finally {
      if (isCurrent()) setGoingBack(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleApprove = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    const isCurrent = () => ownsRun(owner, runId, sequence);
    setApproving(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/approve-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
      if (!isCurrent()) return;
      showToast("Script approved", "success");
      await refreshRun(run.id);
    } catch (err) {
      if (isCurrent()) showToast(err instanceof Error ? err.message : "Approve failed", "error");
    } finally {
      if (isCurrent()) setApproving(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleGenerate = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    const isCurrent = () => ownsRun(owner, runId, sequence);
    setGenerating(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/generate-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!isCurrent()) return;
      showToast("Script generation started");
      scheduleRefresh(runId, sequence);
    } catch (err) {
      if (isCurrent()) showToast(err instanceof Error ? err.message : "Generate failed", "error");
    } finally {
      if (isCurrent()) setGenerating(false);
    }
  }, [run, numericProjectId, modelSelection.script_model, scheduleRefresh, showToast, ownsRun]);

  const handleRestart = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setRestarting(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "SCRIPT_GENERATING" }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      // Dispatch script generation task after stage reset
      await apiVoid(`${API_BASE}/runs/${run.id}/generate-script`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Restarting script generation\u2026");
      scheduleRefresh(runId, sequence);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Restart failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setRestarting(false);
    }
  }, [run, numericProjectId, modelSelection.script_model, scheduleRefresh, showToast, ownsRun]);

  const handleApproveVisualPlan = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setApproving(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/approve-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Visual plan approved", "success");
      await refreshRun(run.id);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Approve failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setApproving(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleGenerateVisualPlan = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setGenerating(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Visual plan generation started");
      scheduleRefresh(runId, sequence);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Generate failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setGenerating(false);
    }
  }, [run, numericProjectId, modelSelection.script_model, scheduleRefresh, showToast, ownsRun]);

  const handleRestartVisualPlan = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setRestarting(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/restart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "VISUAL_PLAN_GENERATING" }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      // Dispatch visual plan generation task after stage reset
      await apiVoid(`${API_BASE}/runs/${run.id}/generate-visual-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_key: modelSelection.script_model || "qwen3-4b",
        }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Restarting visual plan generation\u2026");
      scheduleRefresh(runId, sequence);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Restart failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setRestarting(false);
    }
  }, [run, numericProjectId, modelSelection.script_model, scheduleRefresh, showToast, ownsRun]);

  const handleRender = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setGenerating(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          render_profile: modelSelection.render_profile || "shorts_default",
        }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Render started");
      await refreshRun(run.id);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Render failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setGenerating(false);
    }
  }, [run, numericProjectId, modelSelection.render_profile, refreshRun, showToast, ownsRun]);

  const handleApproveFinal = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setApproving(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/approve-final`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "agent" }),
      });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Published", "success");
      await refreshRun(run.id);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Publish failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setApproving(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleStop = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setStopping(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/stop`, { method: "POST" });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Run stopped");
      await refreshRun(run.id);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Stop failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setStopping(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleResume = useCallback(async () => {
    if (!run) return;
    const owner = numericProjectId;
    const runId = run.id;
    const sequence = ownerSequence.current;
    setResuming(true);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/resume`, { method: "POST" });
      if (!ownsRun(owner, runId, sequence)) return;
      showToast("Run resumed");
      await refreshRun(run.id);
    } catch (err) {
      if (ownsRun(owner, runId, sequence)) showToast(err instanceof Error ? err.message : "Resume failed", "error");
    } finally {
      if (ownsRun(owner, runId, sequence)) setResuming(false);
    }
  }, [run, numericProjectId, refreshRun, showToast, ownsRun]);

  const handleDeleteProject = useCallback(async () => {
    const owner = numericProjectId;
    const sequence = ownerSequence.current;
    setDeleting(true);
    try {
      await apiVoid(`${API_BASE}/projects/${numericProjectId}`, { method: "DELETE" });
      if (mounted.current && activeProjectId.current === owner && ownerSequence.current === sequence) navigate("/runs");
    } catch (err) {
      if (mounted.current && activeProjectId.current === owner && ownerSequence.current === sequence) showToast(err instanceof Error ? err.message : "Delete failed", "error");
    } finally {
      if (mounted.current && activeProjectId.current === owner && ownerSequence.current === sequence) setDeleting(false);
    }
  }, [numericProjectId, navigate, showToast]);

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
    handleApproveFinal,
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
    toast,
    showToast,
    confirmAction,
    setConfirmAction,
    titleDraft,
    setTitleDraft,
    scriptVersion,
    setScriptVersion,
  };
}
