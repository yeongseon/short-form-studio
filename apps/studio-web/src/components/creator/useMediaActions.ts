import { useState, useCallback, useLayoutEffect, useRef } from "react";
import { apiFetch, API_BASE } from "../../api/client";

import type {
  StoryboardResponse,
  ParagraphAudioParams,
  ParagraphSubtitlesParams,
} from "../../api/storyboard";
import {
  generateParagraphAudio,
  generateParagraphSubtitles,
  generateAllParagraphAudio,
  generateAllParagraphSubtitles,
} from "../../api/storyboard";

interface UseMediaActionsArgs {
  runId: number;
  imageModel?: string;
  ttsModel?: string;
  subtitleModel?: string;
  storyboard: StoryboardResponse | null;
  setStoryboard: React.Dispatch<React.SetStateAction<StoryboardResponse | null>>;
  onStatusMessage?: (msg: string | null) => void;
}

export function useMediaActions({
  runId,
  imageModel,
  ttsModel,
  subtitleModel,
  storyboard,
  setStoryboard,
  onStatusMessage,
}: UseMediaActionsArgs) {
  void storyboard;
  const [bulkGenerating, setBulkGenerating] = useState(false);
  const activeRun = useRef<number | null>(runId);
  const ownerSequence = useRef(0);
  useLayoutEffect(() => {
    activeRun.current = runId;
    ownerSequence.current += 1;
    setBulkGenerating(false);
    return () => { activeRun.current = null; };
  }, [runId]);

  const onGenerateImage = useCallback(
    async (sceneId: string) => {
      if (activeRun.current !== runId) return;
      const sequence = ownerSequence.current;
      try {
        const res = await apiFetch(`${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}/generate-image`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_key: imageModel || "sd15" }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          throw new Error(body?.detail ?? `Image generation failed (${res.status})`);
        }
        if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
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
        if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Image generation failed");
      }
    },
    [runId, imageModel, onStatusMessage, setStoryboard],
  );

  const onGenerateAudio = useCallback(
    async (sectionId: string, params: ParagraphAudioParams = {}) => {
      if (activeRun.current !== runId) return;
      const sequence = ownerSequence.current;
      try {
        await generateParagraphAudio(runId, sectionId, {
          ...params,
          tts_model: params.tts_model || ttsModel,
        });
        if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
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
        if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Audio generation failed");
      }
    },
    [runId, ttsModel, onStatusMessage, setStoryboard],
  );

  const onGenerateSubtitles = useCallback(
    async (sectionId: string, params: ParagraphSubtitlesParams = {}) => {
      if (activeRun.current !== runId) return;
      const sequence = ownerSequence.current;
      try {
        await generateParagraphSubtitles(runId, sectionId, {
          ...params,
          subtitle_model: params.subtitle_model || subtitleModel,
        });
        if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
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
        if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Subtitle generation failed");
      }
    },
    [runId, subtitleModel, onStatusMessage, setStoryboard],
  );

  const onBulkImages = useCallback(async () => {
    if (activeRun.current !== runId) return;
    const sequence = ownerSequence.current;
    setBulkGenerating(true);
    try {
      const res = await apiFetch(`${API_BASE}/runs/${runId}/generate-visual-assets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_key: imageModel || "sd15" }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail ?? `Bulk image generation failed (${res.status})`);
      }
      if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
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
      if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Bulk image generation failed");
    } finally {
      if (activeRun.current === runId && ownerSequence.current === sequence) setBulkGenerating(false);
    }
  }, [runId, imageModel, onStatusMessage, setStoryboard]);

  const onBulkAudio = useCallback(async () => {
    if (activeRun.current !== runId) return;
    const sequence = ownerSequence.current;
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphAudio(runId, { tts_model: ttsModel });
      if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
      const successIds = new Set(
        result.tasks.filter((t) => !t.error).map((t) => t.section_id),
      );
      const failedCount = result.tasks.filter((t) => t.error).length;
      const msg = failedCount > 0
        ? `Audio generation started for ${successIds.size} paragraphs (${failedCount} failed)`
        : `Audio generation started for ${result.total} paragraphs`;
      onStatusMessage?.(msg);
      setStoryboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          paragraphs: prev.paragraphs.map((p) =>
            successIds.has(p.section_id) && !p.audio_url
              ? { ...p, status: "generating_audio" as const }
              : p,
          ),
        };
      });
    } catch (err) {
      if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Bulk audio generation failed");
    } finally {
      if (activeRun.current === runId && ownerSequence.current === sequence) setBulkGenerating(false);
    }
  }, [runId, ttsModel, onStatusMessage, setStoryboard]);

  const onBulkSubtitles = useCallback(async () => {
    if (activeRun.current !== runId) return;
    const sequence = ownerSequence.current;
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphSubtitles(runId, { subtitle_model: subtitleModel });
      if (activeRun.current !== runId || ownerSequence.current !== sequence) return;
      const successIds = new Set(
        result.tasks.filter((t) => !t.error).map((t) => t.section_id),
      );
      const failedCount = result.tasks.filter((t) => t.error).length;
      const msg = failedCount > 0
        ? `Subtitle generation started for ${successIds.size} paragraphs (${failedCount} failed)`
        : `Subtitle generation started for ${result.total} paragraphs`;
      onStatusMessage?.(msg);
      setStoryboard((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          paragraphs: prev.paragraphs.map((p) =>
            successIds.has(p.section_id) && p.audio_url && !p.subtitles_url
              ? { ...p, status: "generating_subtitles" as const }
              : p,
          ),
        };
      });
    } catch (err) {
      if (activeRun.current === runId && ownerSequence.current === sequence) onStatusMessage?.(err instanceof Error ? err.message : "Bulk subtitle generation failed");
    } finally {
      if (activeRun.current === runId && ownerSequence.current === sequence) setBulkGenerating(false);
    }
  }, [runId, subtitleModel, onStatusMessage, setStoryboard]);

  return {
    onGenerateImage,
    onGenerateAudio,
    onGenerateSubtitles,
    onBulkImages,
    onBulkAudio,
    onBulkSubtitles,
    bulkGenerating,
  };
}
