import { useState, useEffect, useCallback, useMemo } from "react";
import { apiFetch, API_BASE } from "../../api/client";
import { type VisualScene } from "../../types/api";

export type { VisualScene } from "../../types/api";

const VISUAL_PLAN_FLOW_STAGES = new Set([
  "VISUAL_PLAN_SETUP",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_PLAN_REVIEW",
  "VISUAL_ASSET_GENERATING",
  "VISUAL_ASSET_REVIEW",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

interface VisualFieldState {
  prompt: string;
  mood: string | null;
  composition: string | null;
  style_tags: string[];
  prompt_source: "auto_generated" | "user_edited" | "model_suggested";
  generation_status: "pending" | "generating" | "completed" | "failed";
  dirty?: boolean;
  saving?: boolean;
}

export function useVisualPlanManager(
  runId: number,
  currentStage: string,
  onStatusMessage?: (msg: string | null) => void,
) {
  const [visualScenes, setVisualScenes] = useState<Record<string, VisualScene>>({});
  const [savedVisualScenes, setSavedVisualScenes] = useState<Record<string, VisualScene>>({});
  const [visualVersion, setVisualVersion] = useState<number | null>(null);
  const [visualError, setVisualError] = useState<string | null>(null);
  const [dirtyVisualSceneIds, setDirtyVisualSceneIds] = useState<Set<string>>(new Set());
  const [savingVisualSceneId, setSavingVisualSceneId] = useState<string | null>(null);

  const refreshVisualPlan = useCallback(async () => {
    if (!VISUAL_PLAN_FLOW_STAGES.has(currentStage)) {
      setVisualScenes({});
      setSavedVisualScenes({});
      setVisualVersion(null);
      setDirtyVisualSceneIds(new Set());
      setVisualError(null);
      return;
    }

    try {
      const res = await apiFetch(`${API_BASE}/runs/${runId}/visual-plan`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const detail = body?.detail as string | undefined;
        if (detail && detail.toLowerCase().includes("no visual plan")) {
          setVisualScenes({});
          setSavedVisualScenes({});
          setVisualVersion(null);
          setDirtyVisualSceneIds(new Set());
          setVisualError(null);
          return;
        }
        throw new Error(detail ?? `Failed to load visual plan (${res.status})`);
      }

      const data = await res.json();
      const next: Record<string, VisualScene> = {};
      for (const scene of (data.scenes ?? []) as VisualScene[]) {
        next[scene.scene_id] = { ...scene };
      }
      setVisualScenes(next);
      setSavedVisualScenes(next);
      setVisualVersion(data.version ?? null);
      setDirtyVisualSceneIds(new Set());
      setVisualError(null);
    } catch (err) {
      setVisualError(err instanceof Error ? err.message : "Failed to load visual plan");
    }
  }, [currentStage, runId]);

  useEffect(() => {
    void refreshVisualPlan();
  }, [refreshVisualPlan]);

  const onFieldChange = useCallback(
    (
      sceneId: string,
      field: "prompt" | "mood" | "composition" | "style_tags",
      value: string,
    ) => {
      setVisualScenes((prev) => {
        const current = prev[sceneId];
        if (!current) return prev;

        const next = { ...current };
        if (field === "prompt") {
          next.prompt = value;
          next.prompt_edited = true;
          next.prompt_source = "user_edited";
        } else if (field === "mood") {
          next.mood = value.trim() ? value : null;
        } else if (field === "composition") {
          next.composition = value.trim() ? value : null;
        } else if (field === "style_tags") {
          next.style_tags = value
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean);
        }

        return { ...prev, [sceneId]: next };
      });

      setDirtyVisualSceneIds((prev) => {
        if (prev.has(sceneId)) return prev;
        const next = new Set(prev);
        next.add(sceneId);
        return next;
      });
    },
    [],
  );

  const onSaveScene = useCallback(
    async (sceneId: string) => {
      const scene = visualScenes[sceneId];
      const saved = savedVisualScenes[sceneId];
      if (!scene || !saved) return;

      const updates: Record<string, unknown> = {};
      if (scene.prompt !== saved.prompt) updates.prompt = scene.prompt;
      if (scene.prompt_edited !== saved.prompt_edited) updates.prompt_edited = scene.prompt_edited;
      if (scene.prompt_source !== saved.prompt_source) updates.prompt_source = scene.prompt_source;
      if (scene.mood !== saved.mood) updates.mood = scene.mood;
      if (scene.composition !== saved.composition) updates.composition = scene.composition;
      if (JSON.stringify(scene.style_tags) !== JSON.stringify(saved.style_tags)) {
        updates.style_tags = scene.style_tags;
      }
      if (visualVersion !== null) updates.expected_version = visualVersion;
      if (Object.keys(updates).length === 0) return;

      setSavingVisualSceneId(sceneId);
      setVisualError(null);
      try {
        const res = await apiFetch(`${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(updates),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `Failed to save scene (${res.status})`);
        }

        const data = await res.json();
        const next: Record<string, VisualScene> = {};
        for (const visualScene of (data.scenes ?? []) as VisualScene[]) {
          next[visualScene.scene_id] = { ...visualScene };
        }
        setVisualScenes(next);
        setSavedVisualScenes(next);
        setVisualVersion(data.version ?? visualVersion);
        setDirtyVisualSceneIds((prev) => {
          const copy = new Set(prev);
          copy.delete(sceneId);
          return copy;
        });
        onStatusMessage?.(`Saved visual details for ${sceneId}`);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to save visual details";
        setVisualError(message);
        onStatusMessage?.(message);
      } finally {
        setSavingVisualSceneId(null);
      }
    },
    [visualScenes, savedVisualScenes, visualVersion, runId, onStatusMessage],
  );

  const visualFieldBySceneId = useMemo(() => {
    const out: Record<string, VisualFieldState> = {};

    for (const [sceneId, scene] of Object.entries(visualScenes)) {
      out[sceneId] = {
        prompt: scene.prompt,
        mood: scene.mood,
        composition: scene.composition,
        style_tags: scene.style_tags,
        prompt_source: scene.prompt_source,
        generation_status: scene.generation_status,
        dirty: dirtyVisualSceneIds.has(sceneId),
        saving: savingVisualSceneId === sceneId,
      };
    }
    return out;
  }, [visualScenes, dirtyVisualSceneIds, savingVisualSceneId]);

  return {
    visualFieldBySceneId,
    onFieldChange,
    onSaveScene,
    refreshVisualPlan,
    visualError,
    visualVersion,
  };
}
