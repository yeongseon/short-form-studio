/**
 * StoryboardWorkspace — composes PipelineOverviewBar + BulkActionBar + SceneCardGrid.
 *
 * Fetches storyboard data, handles polling during generation,
 * and wires up per-scene and bulk API calls.
 */

import { useState, useEffect, useCallback } from "react";

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

// --------------- props ---------------

export interface StoryboardWorkspaceProps {
  runId: number;
  /** TTS model key from parent model selection. */
  ttsModel?: string;
  /** STT model key from parent model selection. */
  subtitleModel?: string;
  /** Image model key from parent model selection. */
  imageModel?: string;
  /** Polling interval in ms (default 4000). */
  pollInterval?: number;
  /** Status message callback. */
  onStatusMessage?: (msg: string) => void;
  /** Called when render should be triggered. */
  onRender?: () => void;
  /** True when render is in progress. */
  rendering?: boolean;
}

// --------------- styles ---------------

const containerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const skeletonStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
  gap: 12,
};

const skeletonCardStyle: React.CSSProperties = {
  height: 160,
  borderRadius: 8,
  background: "linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%)",
  backgroundSize: "200% 100%",
  animation: "assetSlotShimmer 1.5s ease-in-out infinite",
};

// --------------- component ---------------

export default function StoryboardWorkspace({
  runId,
  ttsModel,
  subtitleModel,
  imageModel,
  pollInterval = 4000,
  onStatusMessage,
  onRender,
  rendering = false,
}: StoryboardWorkspaceProps) {
  const [storyboard, setStoryboard] = useState<StoryboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bulkGenerating, setBulkGenerating] = useState(false);

  const hasGenerating = storyboard?.paragraphs.some(
    (p) => p.status.startsWith("generating_"),
  ) ?? false;

  // ---- fetch ----

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

  useEffect(() => {
    loadStoryboard();
  }, [loadStoryboard]);

  // ---- polling ----

  useEffect(() => {
    if (!hasGenerating && !bulkGenerating) return;
    const timer = setInterval(loadStoryboard, pollInterval);
    return () => clearInterval(timer);
  }, [hasGenerating, bulkGenerating, pollInterval, loadStoryboard]);

  // ---- per-scene handlers ----

  const handleGenerateImage = useCallback(
    async (sceneId: string) => {
      try {
        await fetch(
          `${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}/generate-image`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model_key: imageModel || "sd15" }),
          },
        );
        onStatusMessage?.(`Image generation started for scene ${sceneId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.scene_id === sceneId
                ? { ...p, status: "generating_image" as const }
                : p,
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
        onStatusMessage?.(`Audio generation started for §${sectionId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.section_id === sectionId
                ? { ...p, status: "generating_audio" as const }
                : p,
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
        onStatusMessage?.(`Subtitle generation started for §${sectionId}`);
        setStoryboard((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            paragraphs: prev.paragraphs.map((p) =>
              p.section_id === sectionId
                ? { ...p, status: "generating_subtitles" as const }
                : p,
            ),
          };
        });
      } catch (err) {
        onStatusMessage?.(err instanceof Error ? err.message : "Subtitle generation failed");
      }
    },
    [runId, subtitleModel, onStatusMessage],
  );

  // ---- bulk handlers ----

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
            p.audio_url && !p.subtitles_url
              ? { ...p, status: "generating_subtitles" as const }
              : p,
          ),
        };
      });
    } catch (err) {
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk subtitle generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, subtitleModel, onStatusMessage]);

  // ---- render ----

  if (loading) {
    return (
      <div style={containerStyle} data-testid="storyboard-workspace-loading">
        <div style={skeletonStyle}>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} style={skeletonCardStyle} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
        data-testid="storyboard-workspace-error"
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

  return (
    <div style={containerStyle} data-testid="storyboard-workspace">
      <PipelineOverviewBar
        paragraphs={paragraphs}
        totalParagraphs={storyboard.total_paragraphs}
        readyParagraphs={storyboard.ready_paragraphs}
        renderReady={storyboard.render_ready}
        onRender={onRender}
        rendering={rendering}
      />

      <BulkActionBar
        paragraphs={paragraphs}
        generating={bulkGenerating}
        onGenerateAllImages={handleBulkImages}
        onGenerateAllAudio={handleBulkAudio}
        onGenerateAllSubtitles={handleBulkSubtitles}
      />

      <SceneCardGrid
        paragraphs={paragraphs}
        onGenerateImage={handleGenerateImage}
        onGenerateAudio={(sectionId) => handleGenerateAudio(sectionId)}
        onGenerateSubtitles={(sectionId) => handleGenerateSubtitles(sectionId)}
        disabled={bulkGenerating}
      />
    </div>
  );
}
