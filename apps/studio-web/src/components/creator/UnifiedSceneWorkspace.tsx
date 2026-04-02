import { useState, useEffect, useCallback, useMemo } from "react";

import PipelineOverviewBar from "./PipelineOverviewBar";
import BulkActionBar from "./BulkActionBar";
import SceneCardGrid from "./SceneCardGrid";
import type {
  StoryboardResponse,
  ParagraphAudioParams,
  ParagraphSubtitlesParams,
} from "../../api/storyboard";
import {
  fetchStoryboard,
  generateParagraphAudio,
  generateParagraphSubtitles,
  generateAllParagraphAudio,
  generateAllParagraphSubtitles,
} from "../../api/storyboard";

const API_BASE = "/api/creator";

interface VisualScene {
  scene_id: string;
  prompt: string;
  prompt_edited: boolean;
  prompt_source: "auto_generated" | "user_edited" | "model_suggested";
  style_tags: string[];
  mood: string | null;
  composition: string | null;
  generation_status: "pending" | "generating" | "completed" | "failed";
}

export interface UnifiedSceneWorkspaceProps {
  runId: number;
  currentStage: string;
  ttsModel?: string;
  subtitleModel?: string;
  imageModel?: string;
  pollInterval?: number;
  onStatusMessage?: (msg: string) => void;
  onRender?: () => void;
  rendering?: boolean;
  stageActionLoading?: boolean;
  onGenerateVisualPlan?: () => void;
  onApproveVisualPlan?: () => void;
  onRegenerateVisualPlan?: () => void;
}

const containerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const skeletonStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const skeletonCardStyle: React.CSSProperties = {
  height: 100,
  borderRadius: 8,
  background: "linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%)",
  backgroundSize: "200% 100%",
  animation: "assetSlotShimmer 1.5s ease-in-out infinite",
};

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

const GENERATING_STAGES = new Set([
  "SCRIPT_GENERATING",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_ASSET_GENERATING",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
]);

const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export default function UnifiedSceneWorkspace({
  runId,
  currentStage,
  ttsModel,
  subtitleModel,
  imageModel,
  pollInterval = 4000,
  onStatusMessage,
  onRender,
  rendering = false,
  stageActionLoading = false,
  onGenerateVisualPlan,
  onApproveVisualPlan,
  onRegenerateVisualPlan,
}: UnifiedSceneWorkspaceProps) {
  const [storyboard, setStoryboard] = useState<StoryboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bulkGenerating, setBulkGenerating] = useState(false);

  const [visualScenes, setVisualScenes] = useState<Record<string, VisualScene>>({});
  const [savedVisualScenes, setSavedVisualScenes] = useState<Record<string, VisualScene>>({});
  const [visualVersion, setVisualVersion] = useState<number | null>(null);
  const [visualError, setVisualError] = useState<string | null>(null);
  const [dirtyVisualSceneIds, setDirtyVisualSceneIds] = useState<Set<string>>(new Set());
  const [savingVisualSceneId, setSavingVisualSceneId] = useState<string | null>(null);

  const hasGeneratingParagraph =
    storyboard?.paragraphs.some((p) => p.status.startsWith("generating_")) ?? false;

  const loadStoryboard = useCallback(async () => {
    try {
      const data = await fetchStoryboard(runId);
      setStoryboard(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load storyboard");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  const loadVisualPlan = useCallback(async () => {
    if (!VISUAL_PLAN_FLOW_STAGES.has(currentStage)) {
      setVisualScenes({});
      setSavedVisualScenes({});
      setVisualVersion(null);
      setDirtyVisualSceneIds(new Set());
      setVisualError(null);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/visual-plan`);
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
    void loadStoryboard();
  }, [loadStoryboard]);

  useEffect(() => {
    void loadVisualPlan();
  }, [loadVisualPlan]);

  useEffect(() => {
    if (!hasGeneratingParagraph && !bulkGenerating && !GENERATING_STAGES.has(currentStage)) {
      return;
    }
    const timer = setInterval(() => {
      void loadStoryboard();
      void loadVisualPlan();
    }, pollInterval);
    return () => clearInterval(timer);
  }, [
    hasGeneratingParagraph,
    bulkGenerating,
    currentStage,
    pollInterval,
    loadStoryboard,
    loadVisualPlan,
  ]);

  const handleGenerateImage = useCallback(
    async (sceneId: string) => {
      try {
        await fetch(`${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}/generate-image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_key: imageModel || "sd15" }),
        });
        onStatusMessage?.(`Image generation started for scene ${sceneId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.scene_id === sceneId ? { ...p, status: "generating_image" as const } : p,
            ),
          };
        });
      } catch (err) {
        onStatusMessage?.(err instanceof Error ? err.message : "Image generation failed");
      }
    },
    [runId, imageModel, onStatusMessage],
  );

  const handleGenerateAudio = useCallback(
    async (sectionId: string, params: ParagraphAudioParams = {}) => {
      try {
        await generateParagraphAudio(runId, sectionId, {
          ...params,
          tts_model: params.tts_model || ttsModel,
        });
        onStatusMessage?.(`Audio generation started for #${sectionId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.section_id === sectionId ? { ...p, status: "generating_audio" as const } : p,
            ),
          };
        });
      } catch (err) {
        onStatusMessage?.(err instanceof Error ? err.message : "Audio generation failed");
      }
    },
    [runId, ttsModel, onStatusMessage],
  );

  const handleGenerateSubtitles = useCallback(
    async (sectionId: string, params: ParagraphSubtitlesParams = {}) => {
      try {
        await generateParagraphSubtitles(runId, sectionId, {
          ...params,
          subtitle_model: params.subtitle_model || subtitleModel,
        });
        onStatusMessage?.(`Subtitle generation started for #${sectionId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.section_id === sectionId ? { ...p, status: "generating_subtitles" as const } : p,
            ),
          };
        });
      } catch (err) {
        onStatusMessage?.(err instanceof Error ? err.message : "Subtitle generation failed");
      }
    },
    [runId, subtitleModel, onStatusMessage],
  );

  const handleBulkImages = useCallback(async () => {
    setBulkGenerating(true);
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/generate-visual-assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_key: imageModel || "sd15" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Bulk image generation failed (${res.status})`);
      }
      onStatusMessage?.("Bulk image generation started");
      setStoryboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          paragraphs: prev.paragraphs.map((p) =>
            !p.image_url ? { ...p, status: "generating_image" as const } : p,
          ),
        };
      });
    } catch (err) {
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk image generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, imageModel, onStatusMessage]);

  const handleBulkAudio = useCallback(async () => {
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphAudio(runId, { tts_model: ttsModel });
      onStatusMessage?.(`Audio generation started for ${result.dispatched} paragraphs`);
      setStoryboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          paragraphs: prev.paragraphs.map((p) =>
            !p.audio_url ? { ...p, status: "generating_audio" as const } : p,
          ),
        };
      });
    } catch (err) {
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk audio generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, ttsModel, onStatusMessage]);

  const handleBulkSubtitles = useCallback(async () => {
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphSubtitles(runId, { subtitle_model: subtitleModel });
      onStatusMessage?.(`Subtitle generation started for ${result.dispatched} paragraphs`);
      setStoryboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          paragraphs: prev.paragraphs.map((p) =>
            p.audio_url && !p.subtitles_url ? { ...p, status: "generating_subtitles" as const } : p,
          ),
        };
      });
    } catch (err) {
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk subtitle generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, subtitleModel, onStatusMessage]);

  const handleVisualFieldChange = useCallback(
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

  const handleSaveVisualFields = useCallback(
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
        const res = await fetch(`${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}`, {
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
    const out: Record<string, {
      prompt: string;
      mood: string | null;
      composition: string | null;
      style_tags: string[];
      prompt_source: "auto_generated" | "user_edited" | "model_suggested";
      generation_status: "pending" | "generating" | "completed" | "failed";
      dirty?: boolean;
      saving?: boolean;
    }> = {};

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

  if (loading) {
    return (
      <div style={containerStyle} data-testid="unified-scene-workspace-loading">
        <div style={skeletonStyle}>
          {SKELETON_KEYS.map((key) => (
            <div key={key} style={skeletonCardStyle} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        data-testid="unified-scene-workspace-error"
        style={{
          padding: "12px 16px",
          background: "#fef2f2",
          border: "1px solid #fca5a5",
          borderRadius: 6,
          color: "#b91c1c",
          fontSize: 13,
        }}
      >
        {error}
        <button
          type="button"
          onClick={loadStoryboard}
          style={{
            marginLeft: 12,
            padding: "2px 10px",
            fontSize: 12,
            border: "1px solid #fca5a5",
            borderRadius: 4,
            background: "#fff",
            cursor: "pointer",
            color: "#b91c1c",
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!storyboard) return null;

  const paragraphs = storyboard.paragraphs;
  const canShowSceneGrid =
    currentStage !== "IDEA_READY" &&
    currentStage !== "SCRIPT_GENERATING" &&
    paragraphs.length > 0;
  const showVisualPlanInfo =
    currentStage === "VISUAL_PLAN_SETUP" || currentStage === "VISUAL_PLAN_GENERATING";

  return (
    <div style={containerStyle} data-testid="unified-scene-workspace">
      {showVisualPlanInfo && (
        <div
          data-testid="visual-plan-stage-info"
          style={{
            padding: "10px 14px",
            borderRadius: 8,
            border: "1px solid #bfdbfe",
            background: "#eff6ff",
            color: "#1e3a8a",
            fontSize: 13,
          }}
        >
          {currentStage === "VISUAL_PLAN_GENERATING"
            ? "Generating visual plan. Scene prompts will populate in this same grid."
            : "Visual plan setup is ready. Generate the visual plan to unlock per-scene image drafting details."}
        </div>
      )}

      {visualError && (
        <div
          role="alert"
          data-testid="visual-plan-inline-error"
          style={{
            padding: "8px 12px",
            borderRadius: 6,
            border: "1px solid #fecaca",
            background: "#fef2f2",
            color: "#b91c1c",
            fontSize: 12,
          }}
        >
          {visualError}
        </div>
      )}

      {(canShowSceneGrid || showVisualPlanInfo) && (
        <>
          <PipelineOverviewBar
            paragraphs={paragraphs}
            totalParagraphs={storyboard.total_paragraphs}
            readyParagraphs={storyboard.ready_paragraphs}
            renderReady={storyboard.render_ready}
            onRender={onRender}
            rendering={rendering}
          />

          <BulkActionBar
            currentStage={currentStage}
            paragraphs={paragraphs}
            generating={bulkGenerating}
            stageActionLoading={stageActionLoading}
            onGenerateVisualPlan={onGenerateVisualPlan}
            onApproveVisualPlan={onApproveVisualPlan}
            onRegenerateVisualPlan={onRegenerateVisualPlan}
            onGenerateAllImages={handleBulkImages}
            onGenerateAllAudio={handleBulkAudio}
            onGenerateAllSubtitles={handleBulkSubtitles}
          />
        </>
      )}

      {canShowSceneGrid ? (
        <SceneCardGrid
          paragraphs={paragraphs}
          currentStage={currentStage}
          visualFieldBySceneId={visualFieldBySceneId}
          onVisualFieldChange={handleVisualFieldChange}
          onSaveVisualFields={handleSaveVisualFields}
          onGenerateImage={handleGenerateImage}
          onGenerateAudio={(sectionId) => handleGenerateAudio(sectionId)}
          onGenerateSubtitles={(sectionId) => handleGenerateSubtitles(sectionId)}
          disabled={bulkGenerating || stageActionLoading}
        />
      ) : (
        <div
          data-testid="unified-scene-workspace-empty"
          style={{
            textAlign: "center",
            padding: 28,
            background: "#f9fafb",
            borderRadius: 8,
            border: "1px dashed #cbd5e1",
            color: "#64748b",
            fontSize: 13,
          }}
        >
          No script scenes yet. Generate or finish script drafting to populate this workspace.
        </div>
      )}
    </div>
  );
}
