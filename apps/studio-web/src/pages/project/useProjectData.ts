import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { apiFetch, apiJson, apiVoid, API_BASE } from "../../api/client";
import type { RunPreview } from "../../api/runPreview";
import {
  FINAL_REVIEW_STAGES,
  type ModelDefaults,
  type ProjectDetail,
  RUN_POLL_STAGES,
  type RunDetail,
} from "./types";

interface UseProjectDataResult {
  project: ProjectDetail | null;
  setProject: React.Dispatch<React.SetStateAction<ProjectDetail | null>>;
  run: RunDetail | null;
  loading: boolean;
  error: string | null;
  preview: RunPreview | null;
  modelSelection: ModelDefaults;
  onModelChange: (category: string, modelKey: string) => void;
  refreshRun: (runId: number) => Promise<void>;
}

export function useProjectData(projectId: number): UseProjectDataResult {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<RunPreview | null>(null);
  const [modelSelection, setModelSelection] = useState<ModelDefaults>({});
  const activeProject = useRef<number | null>(projectId);
  const projectSequence = useRef(0);
  const runSequence = useRef(0);
  const previewSequence = useRef(0);

  useLayoutEffect(() => {
    activeProject.current = projectId;
    projectSequence.current += 1;
    runSequence.current += 1;
    previewSequence.current += 1;
    setProject(null);
    setRun(null);
    setPreview(null);
    setModelSelection({});
    setError(null);
    setLoading(true);
    return () => { activeProject.current = null; };
  }, [projectId]);

  const fetchProjectAndRun = useCallback(async () => {
    if (activeProject.current !== projectId) return;
    const sequence = ++projectSequence.current;
    const ownsResponse = () => activeProject.current === projectId && projectSequence.current === sequence;
    setLoading(true);
    setError(null);
    try {
      const projData = await apiJson<ProjectDetail>(`${API_BASE}/projects/${projectId}`);
      if (!ownsResponse()) return;
      setProject(projData);

      const res = await apiFetch(`${API_BASE}/projects/${projectId}/runs`);
      if (res.ok) {
        const runsData: { runs: RunDetail[]; total: number } = await res.json();
        if (ownsResponse()) {
          runSequence.current += 1;
          setRun(runsData.runs.length > 0 ? runsData.runs[0] : null);
        }
      } else {
        if (ownsResponse()) {
          runSequence.current += 1;
          setRun(null);
        }
      }
    } catch (err) {
      if (ownsResponse()) setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      if (ownsResponse()) setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!Number.isNaN(projectId)) {
      void fetchProjectAndRun();
    }
  }, [projectId, fetchProjectAndRun]);

  const refreshRun = useCallback(async (runId: number) => {
    const owner = activeProject.current;
    if (owner === null || project?.id !== owner || run?.id !== runId) return;
    const sequence = ++runSequence.current;
    try {
      const data = await apiJson<RunDetail>(`${API_BASE}/runs/${runId}`);
      if (activeProject.current === owner && runSequence.current === sequence && data.project_id === owner) setRun(data);
    } catch {
      return;
    }
  }, [project?.id, run?.id]);

  useEffect(() => {
    if (!run || !RUN_POLL_STAGES.has(run.current_stage)) return;
    const timer = setInterval(() => {
      void refreshRun(run.id);
    }, 3000);
    return () => clearInterval(timer);
  }, [run, refreshRun]);

  useEffect(() => {
    if (!run || !FINAL_REVIEW_STAGES.has(run.current_stage)) {
      previewSequence.current += 1;
      setPreview(null);
      return;
    }
    const owner = projectId;
    const runId = run.id;
    const sequence = ++previewSequence.current;
    (async () => {
      try {
        const res = await apiFetch(`${API_BASE}/runs/${runId}/preview`);
        if (res.ok) {
          const data: RunPreview = await res.json();
          if (activeProject.current === owner && previewSequence.current === sequence) setPreview(data);
        }
      } catch {
        return;
      }
    })();
  }, [projectId, run]);

  useEffect(() => {
    if (run?.model_defaults) {
      setModelSelection((prev) => {
        const hasLocal = Object.keys(prev).length > 0;
        if (hasLocal) return prev;
        return { ...run.model_defaults };
      });
    }
  }, [run?.model_defaults]);

  const onModelChange = useCallback(
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

      const previousValue = modelSelection[field];
      const owner = projectId;

      setModelSelection((prev) => ({ ...prev, [field]: modelKey }));

      if (run) {
        void (async () => {
          try {
            await apiVoid(`${API_BASE}/runs/${run.id}/model-defaults`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ [field]: modelKey }),
            });
          } catch (err) {
            if (activeProject.current !== owner) return;
            setModelSelection((prev) => {
              if (prev[field] !== modelKey) return prev;
              if (previousValue === undefined) {
                const next = { ...prev };
                delete next[field];
                return next;
              }
              return { ...prev, [field]: previousValue };
            });
            console.error("Failed to persist model-default change", err);
          }
        })();
      }
    },
    [modelSelection, projectId, run],
  );

  return {
    project,
    setProject,
    run,
    loading,
    error,
    preview,
    modelSelection,
    onModelChange,
    refreshRun,
  };
}
