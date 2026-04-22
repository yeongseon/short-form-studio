/**
 * StoryboardView — unified grid of all paragraphs for a run.
 *
 * Renders StoryboardCard for each paragraph in a scrollable grid,
 * with bulk action buttons (generate all audio, generate all subtitles)
 * and a render-ready indicator.
 */

import { useState, useEffect, useCallback } from "react";

import StoryboardCard from "./StoryboardCard";
import type {
  StoryboardResponse,
  StoryboardParagraph,
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

// --------------- props ---------------

export interface StoryboardViewProps {
  runId: number;
  readOnly?: boolean;
  onStatusMessage?: (msg: string) => void;
  /** Called when render should be triggered (all paragraphs ready). */
  onRenderReady?: () => void;
  /** Polling interval in ms. Default 5000. */
  pollInterval?: number;
  /** Current pipeline stage, used to keep polling during long-running stages. */
  currentStage?: string;
  /** TTS model key passed from parent model selection */
  ttsModel?: string;
  /** Subtitle (STT) model key passed from parent model selection */
  subtitleModel?: string;
}

// --------------- styles ---------------

const containerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
};

const headerBarStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "12px 16px",
  background: "#fafafa",
  borderRadius: 8,
  border: "1px solid #e5e7eb",
};

const bulkBtnStyle: React.CSSProperties = {
  padding: "6px 14px",
  fontSize: 12,
  fontWeight: 600,
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#fff",
  cursor: "pointer",
  color: "#374151",
  transition: "all 0.15s",
};

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
  gap: 16,
};

const progressBarOuter: React.CSSProperties = {
  height: 6,
  background: "#e5e7eb",
  borderRadius: 3,
  overflow: "hidden",
  flex: 1,
  marginRight: 10,
};

// --------------- component ---------------

export default function StoryboardView({
  runId,
  readOnly = false,
  onStatusMessage,
  onRenderReady,
  pollInterval = 5000,
  currentStage,
  ttsModel,
  subtitleModel,
}: StoryboardViewProps) {
  const [storyboard, setStoryboard] = useState<StoryboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bulkGenerating, setBulkGenerating] = useState(false);

  // Track whether any paragraph is actively generating
  const hasGenerating = storyboard?.paragraphs.some(
    (p) => p.status.startsWith("generating_"),
  ) ?? false;
  const stageImpliesPolling = currentStage === "AUDIO_GENERATING" || currentStage === "SUBTITLE_GENERATING" || currentStage === "RENDER_GENERATING";

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

  // Initial fetch
  useEffect(() => {
    loadStoryboard();
  }, [loadStoryboard]);

  // Polling while generating
  useEffect(() => {
    if (!hasGenerating && !bulkGenerating && !stageImpliesPolling) return;
    const timer = setInterval(() => {
      loadStoryboard();
    }, pollInterval);
    return () => clearInterval(timer);
  }, [hasGenerating, bulkGenerating, stageImpliesPolling, pollInterval, loadStoryboard]);

  // Notify when render-ready
  useEffect(() => {
    if (storyboard?.render_ready) {
      onRenderReady?.();
    }
  }, [storyboard?.render_ready, onRenderReady]);

  // ---- handlers ----

  const handleGenerateAudio = useCallback(
    async (sectionId: string, params: ParagraphAudioParams) => {
      try {
        await generateParagraphAudio(runId, sectionId, { ...params, tts_model: params.tts_model || ttsModel });
        onStatusMessage?.(`Audio generation started for §${sectionId}`);
        // Update local state to show generating
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
    [runId, onStatusMessage, ttsModel],
  );

  const handleGenerateSubtitles = useCallback(
    async (sectionId: string, params: ParagraphSubtitlesParams) => {
      try {
        await generateParagraphSubtitles(runId, sectionId, { ...params, subtitle_model: params.subtitle_model || subtitleModel });
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
    [runId, onStatusMessage, subtitleModel],
  );

  const handleBulkAudio = useCallback(async () => {
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphAudio(runId, { tts_model: ttsModel });
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
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk audio generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, onStatusMessage, ttsModel]);

  const handleBulkSubtitles = useCallback(async () => {
    setBulkGenerating(true);
    try {
      const result = await generateAllParagraphSubtitles(runId, { subtitle_model: subtitleModel });
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
      onStatusMessage?.(err instanceof Error ? err.message : "Bulk subtitle generation failed");
    } finally {
      setBulkGenerating(false);
    }
  }, [runId, onStatusMessage, subtitleModel]);

  // ---- render ----

  if (loading) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: 32,
          color: "#6b7280",
          fontSize: 13,
        }}
      >
        Loading storyboard…
      </div>
    );
  }

  if (error) {
    return (
      <div
        role="alert"
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

  if (!storyboard || storyboard.paragraphs.length === 0) {
    return (
      <div
        style={{
          textAlign: "center",
          padding: 32,
          color: "#6b7280",
          fontSize: 13,
          background: "#f9fafb",
          borderRadius: 8,
          border: "1px dashed #d1d5db",
        }}
      >
        No paragraphs in storyboard. Generate a script and visual plan first.
      </div>
    );
  }

  const paragraphs: StoryboardParagraph[] = storyboard.paragraphs;
  const readyCount = storyboard.ready_paragraphs;
  const totalCount = storyboard.total_paragraphs;
  const progress = totalCount > 0 ? (readyCount / totalCount) * 100 : 0;

  // Count paragraphs with audio / subtitles
  const audioCount = paragraphs.filter((p) => p.audio_url).length;
  const subtitleCount = paragraphs.filter((p) => p.subtitles_url).length;

  return (
    <div style={containerStyle} data-testid="storyboard-view">
      {/* Header bar with progress + bulk actions */}
      <div style={headerBarStyle}>
        <div style={{ display: "flex", alignItems: "center", flex: 1, gap: 12 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#111827", whiteSpace: "nowrap" }}>
            Storyboard
          </div>
          <div style={progressBarOuter}>
            <div
              style={{
                height: "100%",
                width: `${progress}%`,
                background: storyboard.render_ready ? "#22c55e" : "#4285f4",
                borderRadius: 3,
                transition: "width 0.3s ease",
              }}
            />
          </div>
          <span style={{ fontSize: 12, color: "#6b7280", whiteSpace: "nowrap" }}>
            {readyCount}/{totalCount} ready
          </span>
        </div>

        {!readOnly && (
          <div style={{ display: "flex", gap: 8, marginLeft: 16 }}>
            <button
              type="button"
              style={{
                ...bulkBtnStyle,
                borderColor: "#fde68a",
                background: "#fffbeb",
                color: "#92400e",
                opacity: bulkGenerating || hasGenerating ? 0.6 : 1,
              }}
              disabled={bulkGenerating || hasGenerating}
              onClick={handleBulkAudio}
              data-testid="bulk-generate-audio"
            >
              {audioCount > 0 ? `Regen All Audio (${audioCount}/${totalCount})` : "Generate All Audio"}
            </button>
            <button
              type="button"
              style={{
                ...bulkBtnStyle,
                borderColor: "#bae6fd",
                background: "#f0f9ff",
                color: "#075985",
                opacity: bulkGenerating || hasGenerating || audioCount === 0 ? 0.6 : 1,
              }}
              disabled={bulkGenerating || hasGenerating || audioCount === 0}
              onClick={handleBulkSubtitles}
              data-testid="bulk-generate-subtitles"
            >
              {subtitleCount > 0 ? `Regen All Subs (${subtitleCount}/${totalCount})` : "Generate All Subtitles"}
            </button>
            <button
              type="button"
              style={{ ...bulkBtnStyle, color: "#6b7280" }}
              onClick={loadStoryboard}
              title="Refresh storyboard data"
            >
              Refresh
            </button>
          </div>
        )}
      </div>

      {/* Render-ready banner */}
      {storyboard.render_ready && (
        <div
          data-testid="render-ready-banner"
          style={{
            padding: "10px 16px",
            background: "#f0fdf4",
            border: "1px solid #bbf7d0",
            borderRadius: 8,
            color: "#166534",
            fontSize: 13,
            fontWeight: 600,
            textAlign: "center",
          }}
        >
          All paragraphs are ready — you can now render the video.
        </div>
      )}

      {/* Paragraph cards grid */}
      <div style={gridStyle}>
        {paragraphs.map((p) => (
          <StoryboardCard
            key={p.section_id}
            paragraph={p}
            readOnly={readOnly}
            onGenerateAudio={handleGenerateAudio}
            onGenerateSubtitles={handleGenerateSubtitles}
          />
        ))}
      </div>

      {/* Summary footer */}
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          gap: 16,
          padding: "8px 0",
          fontSize: 12,
          color: "#9ca3af",
        }}
      >
        <span>{totalCount} paragraphs</span>
        <span>·</span>
        <span>{audioCount} audio</span>
        <span>·</span>
        <span>{subtitleCount} subtitles</span>
        {storyboard.render_ready && (
          <>
            <span>·</span>
            <span style={{ color: "#22c55e", fontWeight: 600 }}>Render Ready</span>
          </>
        )}
      </div>
    </div>
  );
}
