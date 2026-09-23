import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiJson, API_BASE } from "../../api/client";
import type { RunPreview } from "../../api/runPreview";
import type { RunDetail, VisualPlanScene } from "../../types/api";

export interface ScriptData {
  readonly script: string | null;
  readonly structured_script: Record<string, unknown> | null;
}
export type LegacyVisualPlanScene = VisualPlanScene & { description?: string; image_prompt?: string };
export type ReviewAssets = Record<string, { id: number; asset_path: string; model_used: string; is_active: boolean }[]>;

const POST_SCRIPT_STAGES = new Set(["SCRIPT_REVIEW", "VISUAL_PLAN_GENERATING", "VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW", "AUDIO_GENERATING", "SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW", "PUBLISHED"]);
const POST_VISUAL_PLAN_STAGES = new Set(["VISUAL_PLAN_REVIEW", "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW", "AUDIO_GENERATING", "SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW", "PUBLISHED"]);
const POST_VISUAL_ASSET_STAGES = new Set(["VISUAL_ASSET_REVIEW", "AUDIO_GENERATING", "SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW", "PUBLISHED"]);
export const POST_AUDIO_STAGES = new Set(["SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW", "PUBLISHED"]);

export function useReviewData(runId: number) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [preview, setPreview] = useState<RunPreview | null>(null);
  const [script, setScript] = useState<ScriptData | null>(null);
  const [scenes, setScenes] = useState<LegacyVisualPlanScene[]>([]);
  const [assets, setAssets] = useState<ReviewAssets>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refreshRun = useCallback(async () => {
    setRun(await apiJson<RunDetail>(`${API_BASE}/runs/${runId}`));
  }, [runId]);

  useEffect(() => {
    if (Number.isNaN(runId)) return;
    let active = true;
    setLoading(true);
    setError(null);
    setScript(null);
    setScenes([]);
    setAssets({});
    setPreview(null);
    const load = async () => {
      try {
        const data = await apiJson<RunDetail>(`${API_BASE}/runs/${runId}`);
        if (!active) return;
        setRun(data);
        const stage = data.current_stage;
        if (data.metadata?.render_source !== "timeline") {
          if (POST_SCRIPT_STAGES.has(stage)) {
            const response = await apiFetch(`${API_BASE}/runs/${runId}/script`);
            if (response.ok) {
              const value: ScriptData = await response.json();
              if (active) setScript(value);
            }
          }
          if (POST_VISUAL_PLAN_STAGES.has(stage)) {
            const response = await apiFetch(`${API_BASE}/runs/${runId}/visual-plan`);
            if (response.ok) {
              const value: { scenes?: LegacyVisualPlanScene[] } = await response.json();
              if (active) setScenes(value.scenes ?? []);
            }
          }
          if (POST_VISUAL_ASSET_STAGES.has(stage)) {
            const response = await apiFetch(`${API_BASE}/runs/${runId}/visual-assets`);
            if (response.ok) {
              const value: { scenes?: ReviewAssets } = await response.json();
              if (active) setAssets(value.scenes ?? {});
            }
          }
        }
        if (POST_AUDIO_STAGES.has(stage)) {
          const response = await apiFetch(`${API_BASE}/runs/${runId}/preview`);
          if (response.ok) {
            const value: RunPreview = await response.json();
            if (active) setPreview(value);
          }
        }
      } catch (err: unknown) {
        if (active) setError(err instanceof Error ? err.message : "An unexpected error occurred");
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    return () => { active = false; };
  }, [runId]);
  return { run, preview, script, scenes, assets, loading, error, refreshRun };
}
