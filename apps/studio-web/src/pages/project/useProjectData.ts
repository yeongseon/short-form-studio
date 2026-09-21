import { useCallback, useEffect, useState } from "react";

import { apiFetch, apiJson, apiVoid, API_BASE } from "../../api/client";
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
  preview: Record<string, unknown> | null;
  modelSelection: ModelDefaults;
  onModelChange: (category: string, modelKey: string) => void;
  refreshRun: (runId: number) => Promise<void>;
}

export function useProjectData(projectId: number): UseProjectDataResult {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [modelSelection, setModelSelection] = useState<ModelDefaults>({});

  const fetchProjectAndRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const projData = await apiJson<ProjectDetail>(`${API_BASE}/projects/${projectId}`);
      setProject(projData);

      const res = await apiFetch(`${API_BASE}/projects/${projectId}/runs`);
      if (res.ok) {
        const runsData: { runs: RunDetail[]; total: number } = await res.json();
        setRun(runsData.runs.length > 0 ? runsData.runs[0] : null);
      } else {
        setRun(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (!Number.isNaN(projectId)) {
      void fetchProjectAndRun();
    }
  }, [projectId, fetchProjectAndRun]);

  const refreshRun = useCallback(async (runId: number) => {
    try {
      const data = await apiJson<RunDetail>(`${API_BASE}/runs/${runId}`);
      setRun(data);
    } catch {
      return;
    }
  }, []);

  useEffect(() => {
    if (!run || !RUN_POLL_STAGES.has(run.current_stage)) return;
    const timer = setInterval(() => {
      void refreshRun(run.id);
    }, 3000);
    return () => clearInterval(timer);
  }, [run, refreshRun]);

  useEffect(() => {
    if (!run || !FINAL_REVIEW_STAGES.has(run.current_stage)) {
      setPreview(null);
      return;
    }
    (async () => {
      try {
        const res = await apiFetch(`${API_BASE}/runs/${run.id}/preview`);
        if (res.ok) {
          const data = await res.json();
          setPreview(data);
        }
      } catch {
        return;
      }
    })();
  }, [run]);

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
            setModelSelection((prev) => {
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
    [modelSelection, run],
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
