/**
 * SceneCard — compact card for a single scene (paragraph) in the storyboard.
 *
 * Displays: scene number, status badge, script text (truncated),
 * and 3 AssetSlots (image, audio, subtitle).
 * Per-scene generate/regenerate actions available.
 */

import { useState } from "react";

import AssetSlot from "./AssetSlot";
import type { AssetStatus } from "./AssetSlot";
import type { StoryboardParagraph } from "../../api/storyboard";

// --------------- helpers ---------------

/** Convert API artifact path → browser URL via Vite proxy. */
function artifactUrl(path: string): string {
  const match = path.match(/data\/artifacts\/(.*)/);
  return match ? `/artifacts/${match[1]}` : `/artifacts/${path}`;
}

type SceneStatus = "idle" | "partial" | "generating" | "ready";

function deriveSceneStatus(p: StoryboardParagraph): SceneStatus {
  if (p.status.startsWith("generating_")) return "generating";
  const slotCount = [p.image_url, p.audio_url, p.subtitles_url].filter(Boolean).length;
  if (slotCount === 3) return "ready";
  if (slotCount > 0) return "partial";
  return "idle";
}

function assetStatus(url: string | null, isGenerating: boolean): AssetStatus {
  if (isGenerating) return "loading";
  if (url) return "ready";
  return "empty";
}

const STATUS_BADGE: Record<SceneStatus, { bg: string; border: string; color: string; label: string }> = {
  idle: { bg: "#f9fafb", border: "#e5e7eb", color: "#6b7280", label: "Idle" },
  partial: { bg: "#fffbeb", border: "#fde68a", color: "#92400e", label: "Partial" },
  generating: { bg: "#eff6ff", border: "#bfdbfe", color: "#1e40af", label: "Generating…" },
  ready: { bg: "#f0fdf4", border: "#bbf7d0", color: "#166534", label: "Ready" },
};

// --------------- props ---------------

export interface SceneCardProps {
  paragraph: StoryboardParagraph;
  /** Called to generate or regenerate the image for this scene. */
  onGenerateImage?: (sceneId: string) => void;
  /** Called to generate or regenerate audio for this scene. */
  onGenerateAudio?: (sectionId: string) => void;
  /** Called to generate or regenerate subtitles for this scene. */
  onGenerateSubtitles?: (sectionId: string) => void;
  /** Disable all actions (e.g. during bulk generation). */
  disabled?: boolean;
}

// --------------- styles ---------------

const cardStyle: React.CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  background: "#fff",
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
  transition: "box-shadow 0.15s",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "6px 10px",
  borderBottom: "1px solid #f3f4f6",
  background: "#fafafa",
};

const textStyle: React.CSSProperties = {
  padding: "6px 10px",
  fontSize: 12,
  lineHeight: 1.45,
  color: "#374151",
  overflow: "hidden",
  display: "-webkit-box",
  WebkitLineClamp: 2,
  WebkitBoxOrient: "vertical",
  cursor: "default",
};

const expandedTextStyle: React.CSSProperties = {
  ...textStyle,
  WebkitLineClamp: undefined as unknown as number,
  overflow: "visible",
  display: "block",
};

const slotsStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 4,
  padding: "6px 10px 8px",
};

const actionRowStyle: React.CSSProperties = {
  display: "flex",
  gap: 4,
  padding: "0 10px 8px",
  flexWrap: "wrap",
};

const actionBtnStyle: React.CSSProperties = {
  padding: "3px 8px",
  fontSize: 10,
  fontWeight: 500,
  border: "1px solid #d1d5db",
  borderRadius: 4,
  background: "#fff",
  cursor: "pointer",
  color: "#374151",
  transition: "all 0.15s",
};

// --------------- component ---------------

export default function SceneCard({
  paragraph,
  onGenerateImage,
  onGenerateAudio,
  onGenerateSubtitles,
  disabled = false,
}: SceneCardProps) {
  const p = paragraph;
  const sceneStatus = deriveSceneStatus(p);
  const badge = STATUS_BADGE[sceneStatus];
  const [expanded, setExpanded] = useState(false);

  const isGeneratingImage = p.status === "generating_image";
  const isGeneratingAudio = p.status === "generating_audio";
  const isGeneratingSubs = p.status === "generating_subtitles";
  const isGenerating = p.status.startsWith("generating_");

  return (
    <div
      style={cardStyle}
      data-testid={`scene-card-${p.section_id}`}
      data-status={sceneStatus}
    >
      {/* Header: scene number + status badge */}
      <div style={headerStyle}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#111827" }}>
          Scene {p.order + 1}
        </span>
        <span
          data-testid={`scene-badge-${p.section_id}`}
          style={{
            fontSize: 10,
            fontWeight: 600,
            padding: "1px 6px",
            borderRadius: 8,
            background: badge.bg,
            border: `1px solid ${badge.border}`,
            color: badge.color,
          }}
        >
          {badge.label}
        </span>
      </div>

      {/* Script text (truncated, click to expand) */}
      <div
        style={expanded ? expandedTextStyle : textStyle}
        onClick={() => setExpanded(!expanded)}
        title={expanded ? "Click to collapse" : "Click to expand"}
        data-testid={`scene-text-${p.section_id}`}
      >
        {p.display_text ?? p.text}
      </div>

      {/* Asset slots */}
      <div style={slotsStyle}>
        <AssetSlot
          type="image"
          status={assetStatus(p.image_url, isGeneratingImage)}
          url={p.image_url}
          onRegenerate={
            p.image_url && onGenerateImage && p.scene_id
              ? () => onGenerateImage(p.scene_id!)
              : undefined
          }
          disabled={disabled || isGenerating}
        />
        <AssetSlot
          type="audio"
          status={assetStatus(p.audio_url, isGeneratingAudio)}
          url={p.audio_url}
          duration={p.audio_duration}
          onRegenerate={
            p.audio_url && onGenerateAudio
              ? () => onGenerateAudio(p.section_id)
              : undefined
          }
          disabled={disabled || isGenerating}
        />
        <AssetSlot
          type="subtitle"
          status={assetStatus(p.subtitles_url, isGeneratingSubs)}
          url={p.subtitles_url}
          subtitleCount={p.subtitle_entries?.length ?? null}
          onRegenerate={
            p.subtitles_url && onGenerateSubtitles
              ? () => onGenerateSubtitles(p.section_id)
              : undefined
          }
          disabled={disabled || isGenerating}
        />
      </div>

      {/* Per-scene action buttons (only when not generating) */}
      {!isGenerating && !disabled && (
        <div style={actionRowStyle}>
          {!p.image_url && p.scene_id && onGenerateImage && (
            <button
              type="button"
              style={{ ...actionBtnStyle, borderColor: "#e9d5ff", color: "#6b21a8" }}
              onClick={() => onGenerateImage(p.scene_id!)}
              data-testid={`gen-image-${p.section_id}`}
            >
              Gen Image
            </button>
          )}
          {!p.audio_url && p.image_url && onGenerateAudio && (
            <button
              type="button"
              style={{ ...actionBtnStyle, borderColor: "#fde68a", color: "#92400e" }}
              onClick={() => onGenerateAudio(p.section_id)}
              data-testid={`gen-audio-${p.section_id}`}
            >
              Gen Audio
            </button>
          )}
          {!p.subtitles_url && p.audio_url && onGenerateSubtitles && (
            <button
              type="button"
              style={{ ...actionBtnStyle, borderColor: "#bae6fd", color: "#075985" }}
              onClick={() => onGenerateSubtitles(p.section_id)}
              data-testid={`gen-subs-${p.section_id}`}
            >
              Gen Subtitles
            </button>
          )}
        </div>
      )}
    </div>
  );
}
