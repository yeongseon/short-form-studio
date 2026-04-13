/**
 * SceneCard — full-width horizontal card for a single scene (paragraph).
 *
 * Layout: [Image (left) | Content (right: header, script, visual plan info, asset slots, actions)]
 * Shows script text, image prompt, mood, composition, style tags at a glance.
 */

import { useMemo, useState } from "react";

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
  currentStage: string;
  visualFields?: {
    prompt: string;
    mood: string | null;
    composition: string | null;
    style_tags: string[];
    prompt_source: "auto_generated" | "user_edited" | "model_suggested";
    generation_status: "pending" | "generating" | "completed" | "failed";
    dirty?: boolean;
    saving?: boolean;
  };
  onVisualFieldChange?: (
    sceneId: string,
    field: "prompt" | "mood" | "composition" | "style_tags",
    value: string,
  ) => void;
  onSaveVisualFields?: (sceneId: string) => void;
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
  borderRadius: 10,
  background: "#fff",
  overflow: "hidden",
  transition: "box-shadow 0.15s",
};

const cardBodyStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "row",
  gap: 0,
};

const imageColumnStyle: React.CSSProperties = {
  width: 160,
  minHeight: 140,
  flexShrink: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#f9fafb",
  borderRight: "1px solid #f3f4f6",
};

const imagePreviewStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
  display: "block",
};

const imagePlaceholderStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: "100%",
  height: "100%",
  minHeight: 140,
  color: "#d1d5db",
  fontSize: 28,
};

const contentColumnStyle: React.CSSProperties = {
  flex: 1,
  display: "flex",
  flexDirection: "column",
  minWidth: 0,
  padding: "10px 14px",
  gap: 6,
};

const headerRowStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
};

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  textTransform: "uppercase" as const,
  letterSpacing: "0.05em",
  color: "#9ca3af",
  marginBottom: 1,
};

const promptTextStyle: React.CSSProperties = {
  fontSize: 12,
  lineHeight: 1.45,
  color: "#475569",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  padding: "5px 8px",
  background: "#fefce8",
  borderRadius: 6,
  border: "1px solid #fef3c7",
};

const metaRowStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  alignItems: "center",
};

const metaTagStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 3,
  fontSize: 11,
  padding: "2px 8px",
  borderRadius: 4,
  background: "#f1f5f9",
  color: "#475569",
  border: "1px solid #e2e8f0",
};

const slotsRowStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "row",
  gap: 6,
  flexWrap: "wrap",
};

const slotItemStyle: React.CSSProperties = {
  flex: "1 1 0",
  minWidth: 120,
};

const actionBtnStyle: React.CSSProperties = {
  padding: "3px 10px",
  fontSize: 11,
  fontWeight: 500,
  border: "1px solid #d1d5db",
  borderRadius: 4,
  background: "#fff",
  cursor: "pointer",
  color: "#374151",
  transition: "all 0.15s",
};

const visualPanelStyle: React.CSSProperties = {
  padding: "10px 14px",
  borderTop: "1px solid #f3f4f6",
  display: "flex",
  flexDirection: "column",
  gap: 8,
};

const fieldLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: "#475569",
  marginBottom: 2,
  display: "block",
};

const fieldInputStyle: React.CSSProperties = {
  width: "100%",
  border: "1px solid #cbd5e1",
  borderRadius: 4,
  padding: "5px 7px",
  fontSize: 12,
  color: "#1e293b",
  boxSizing: "border-box",
};

// --------------- component ---------------

export default function SceneCard({
  paragraph,
  currentStage,
  visualFields,
  onVisualFieldChange,
  onSaveVisualFields,
  onGenerateImage,
  onGenerateAudio,
  onGenerateSubtitles,
  disabled = false,
}: SceneCardProps) {
  const p = paragraph;
  const sceneStatus = deriveSceneStatus(p);
  const badge = STATUS_BADGE[sceneStatus];
  const [visualExpanded, setVisualExpanded] = useState(false);

  const stageIndex = useMemo(() => {
    const STAGE_ORDER = [
      "IDEA_READY",
      "SCRIPT_GENERATING",
      "SCRIPT_REVIEW",
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
    ];
    return STAGE_ORDER.indexOf(currentStage);
  }, [currentStage]);

  const isGeneratingImage = p.status === "generating_image";
  const isGeneratingAudio = p.status === "generating_audio";
  const isGeneratingSubs = p.status === "generating_subtitles";
  const isGenerating = p.status.startsWith("generating_");
  const showVisualEditor = currentStage === "VISUAL_PLAN_REVIEW" && Boolean(p.scene_id);
  const imageEnabled = stageIndex >= 6;
  const audioEnabled = stageIndex >= 8;
  const subtitleEnabled = stageIndex >= 9;
  const showImagePreview = Boolean(p.image_url);

  const imageSlotDisabled = disabled || isGenerating || !imageEnabled;
  const audioSlotDisabled = disabled || isGenerating || !audioEnabled;
  const subtitleSlotDisabled = disabled || isGenerating || !subtitleEnabled;
  const canSaveVisual = Boolean(
    p.scene_id &&
      visualFields &&
      onSaveVisualFields &&
      onVisualFieldChange,
  );

  // Visual plan metadata to show inline (read-only display)
  const displayPrompt = visualFields?.prompt || p.image_prompt;
  const displayMood = visualFields?.mood;
  const displayComposition = visualFields?.composition;
  const displayStyleTags = visualFields?.style_tags ?? [];
  const hasAnyMeta = Boolean(displayMood || displayComposition || displayStyleTags.length > 0);
  const canEditPrompt = Boolean(p.scene_id && visualFields && onVisualFieldChange);

  return (
    <div
      style={cardStyle}
      data-testid={`scene-card-${p.section_id}`}
      data-status={sceneStatus}
    >
      <div style={cardBodyStyle}>
        {/* Left column: image */}
        <div style={imageColumnStyle}>
          {showImagePreview ? (
            <img
              src={artifactUrl(p.image_url!)}
              alt={`Scene ${p.order + 1}`}
              style={imagePreviewStyle}
              data-testid={`scene-image-${p.section_id}`}
            />
          ) : (
            <div style={imagePlaceholderStyle}>🖼️</div>
          )}
        </div>

        {/* Right column: content */}
        <div style={contentColumnStyle}>
          {/* Header: scene number + status badge */}
          <div style={headerRowStyle}>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>
              Scene {p.order + 1}
              <span style={{ fontWeight: 400, fontSize: 11, color: "#9ca3af", marginLeft: 6 }}>
                {p.section_id}
              </span>
            </span>
            <span
              data-testid={`scene-badge-${p.section_id}`}
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "1px 8px",
                borderRadius: 8,
                background: badge.bg,
                border: `1px solid ${badge.border}`,
                color: badge.color,
              }}
            >
              {badge.label}
            </span>
          </div>

          {/* Structured metadata: type, speaker, duration, turn_kind */}
          <div style={metaRowStyle} data-testid={`scene-structured-meta-${p.section_id}`}>
            {p.section_type && (
              <span style={{ ...metaTagStyle, background: "#dbeafe", borderColor: "#bfdbfe", color: "#1e40af" }}>
                {p.section_type}
              </span>
            )}
            {p.speaker && (
              <span style={{ ...metaTagStyle, background: "#f0fdf4", borderColor: "#bbf7d0", color: "#166534" }}>
                🎙️ {p.speaker}
              </span>
            )}
            {p.duration != null && (
              <span style={metaTagStyle}>
                ⏱️ {p.duration}s
              </span>
            )}
            {p.turn_kind && (
              <span style={metaTagStyle}>
                🔄 {p.turn_kind}
              </span>
            )}
            {p.visual_override && (
              <span style={{ ...metaTagStyle, background: "#fef3c7", borderColor: "#fde68a", color: "#92400e" }}>
                🎨 {p.visual_override.type}{p.visual_override.value ? `: ${p.visual_override.value.substring(0, 40)}…` : ""}
              </span>
            )}
          </div>

          {/* Script text */}
          {(p.display_text || p.text) && (
            <div style={{ margin: "2px 0" }}>
              <div style={sectionLabelStyle}>Script</div>
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.5,
                  color: "#1f2937",
                  padding: "4px 8px",
                  background: "#f9fafb",
                  borderRadius: 6,
                  border: "1px solid #f3f4f6",
                  whiteSpace: "pre-wrap",
                }}
                data-testid={`scene-script-${p.section_id}`}
              >
                {p.display_text || p.text}
              </div>
            </div>
          )}

          {/* Image generation prompt — inline editable */}
          <div>
            <div style={sectionLabelStyle}>Image Prompt</div>
            {canEditPrompt ? (
              <textarea
                style={{
                  ...promptTextStyle,
                  width: "100%",
                  minHeight: 48,
                  resize: "vertical",
                  fontFamily: "inherit",
                  outline: "none",
                  boxSizing: "border-box" as const,
                  cursor: "text",
                }}
                value={displayPrompt ?? ""}
                placeholder="Enter image generation prompt…"
                data-testid={`scene-image-prompt-${p.section_id}`}
                onChange={(e) => {
                  if (p.scene_id && onVisualFieldChange) {
                    onVisualFieldChange(p.scene_id, "prompt", e.target.value);
                  }
                }}
                onBlur={() => {
                  if (p.scene_id && onSaveVisualFields && visualFields?.dirty) {
                    onSaveVisualFields(p.scene_id);
                  }
                }}
              />
            ) : (
              <div
                style={promptTextStyle}
                data-testid={`scene-image-prompt-${p.section_id}`}
              >
                {displayPrompt || <span style={{ color: "#9ca3af", fontStyle: "italic" }}>No prompt yet</span>}
              </div>
            )}
          </div>

          {/* Visual plan metadata: mood, composition, style tags */}
          {hasAnyMeta && (
            <div style={metaRowStyle} data-testid={`scene-meta-${p.section_id}`}>
              {displayMood && (
                <span style={metaTagStyle}>
                  <span style={{ fontSize: 10 }}>🎭</span> {displayMood}
                </span>
              )}
              {displayComposition && (
                <span style={metaTagStyle}>
                  <span style={{ fontSize: 10 }}>📐</span> {displayComposition}
                </span>
              )}
              {displayStyleTags.map((tag) => (
                <span key={tag} style={{ ...metaTagStyle, background: "#ede9fe", borderColor: "#ddd6fe", color: "#6b21a8" }}>
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Asset slots — horizontal row */}
          <div style={slotsRowStyle}>
            <div style={slotItemStyle}>
              <AssetSlot
                type="image"
                status={assetStatus(p.image_url, isGeneratingImage)}
                url={p.image_url}
                onGenerate={
                  !p.image_url && p.scene_id && onGenerateImage && imageEnabled
                    ? () => onGenerateImage(p.scene_id!)
                    : undefined
                }
                onRegenerate={
                  p.image_url && onGenerateImage && p.scene_id
                    ? () => onGenerateImage(p.scene_id!)
                    : undefined
                }
                disabled={imageSlotDisabled}
              />
            </div>
            <div style={slotItemStyle}>
              <AssetSlot
                type="audio"
                status={assetStatus(p.audio_url, isGeneratingAudio)}
                url={p.audio_url}
                duration={p.audio_duration}
                onGenerate={
                  !p.audio_url && p.image_url && onGenerateAudio && audioEnabled
                    ? () => onGenerateAudio(p.section_id)
                    : undefined
                }
                onRegenerate={
                  p.audio_url && onGenerateAudio
                    ? () => onGenerateAudio(p.section_id)
                    : undefined
                }
                disabled={audioSlotDisabled}
              />
            </div>
            <div style={slotItemStyle}>
              <AssetSlot
                type="subtitle"
                status={assetStatus(p.subtitles_url, isGeneratingSubs)}
                url={p.subtitles_url}
                subtitleCount={p.subtitle_entries?.length ?? null}
                onGenerate={
                  !p.subtitles_url && p.audio_url && onGenerateSubtitles && subtitleEnabled
                    ? () => onGenerateSubtitles(p.section_id)
                    : undefined
                }
                onRegenerate={
                  p.subtitles_url && onGenerateSubtitles
                    ? () => onGenerateSubtitles(p.section_id)
                    : undefined
                }
                disabled={subtitleSlotDisabled}
              />
            </div>
          </div>

          {/* Generate actions are now integrated into AssetSlot empty state */}
        </div>
      </div>

      {/* Visual editor panel — expands below the full card */}
      {showVisualEditor && visualFields && (
        <div style={{ borderTop: "1px solid #f3f4f6" }}>
          <button
            type="button"
            onClick={() => setVisualExpanded((prev) => !prev)}
            style={{
              ...actionBtnStyle,
              width: "100%",
              borderRadius: 0,
              border: "none",
              borderBottom: visualExpanded ? "1px solid #f3f4f6" : "none",
              padding: "6px 14px",
              fontSize: 12,
              background: "#fafbff",
              textAlign: "left",
            }}
            data-testid={`scene-visual-toggle-${p.section_id}`}
          >
            {visualExpanded ? "▾ Hide Visual Details" : "▸ Edit Visual Details"}
          </button>
          {visualExpanded && (
            <div style={visualPanelStyle} data-testid={`scene-visual-panel-${p.section_id}`}>
              <div>
                <label htmlFor={`visual-prompt-${p.section_id}`} style={fieldLabelStyle}>Prompt</label>
                <textarea
                  id={`visual-prompt-${p.section_id}`}
                  data-testid={`scene-visual-prompt-${p.section_id}`}
                  style={{ ...fieldInputStyle, minHeight: 64, resize: "vertical", fontFamily: "inherit" }}
                  value={visualFields.prompt}
                  onChange={(e) => p.scene_id && onVisualFieldChange?.(p.scene_id, "prompt", e.target.value)}
                />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <label htmlFor={`visual-mood-${p.section_id}`} style={fieldLabelStyle}>Mood</label>
                  <input
                    id={`visual-mood-${p.section_id}`}
                    data-testid={`scene-visual-mood-${p.section_id}`}
                    style={fieldInputStyle}
                    value={visualFields.mood ?? ""}
                    onChange={(e) => p.scene_id && onVisualFieldChange?.(p.scene_id, "mood", e.target.value)}
                  />
                </div>
                <div>
                  <label htmlFor={`visual-composition-${p.section_id}`} style={fieldLabelStyle}>Composition</label>
                  <input
                    id={`visual-composition-${p.section_id}`}
                    data-testid={`scene-visual-composition-${p.section_id}`}
                    style={fieldInputStyle}
                    value={visualFields.composition ?? ""}
                    onChange={(e) => p.scene_id && onVisualFieldChange?.(p.scene_id, "composition", e.target.value)}
                  />
                </div>
              </div>
              <div>
                <label htmlFor={`visual-style-tags-${p.section_id}`} style={fieldLabelStyle}>Style Tags (comma-separated)</label>
                <input
                  id={`visual-style-tags-${p.section_id}`}
                  data-testid={`scene-visual-style-tags-${p.section_id}`}
                  style={fieldInputStyle}
                  value={visualFields.style_tags.join(", ")}
                  onChange={(e) => p.scene_id && onVisualFieldChange?.(p.scene_id, "style_tags", e.target.value)}
                />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                {visualFields.dirty && (
                  <span style={{ fontSize: 11, color: "#92400e" }} data-testid={`scene-visual-dirty-${p.section_id}`}>
                    Unsaved changes
                  </span>
                )}
                <span style={{ marginLeft: "auto" }} />
                <button
                  type="button"
                  data-testid={`scene-visual-save-${p.section_id}`}
                  style={{
                    ...actionBtnStyle,
                    borderColor: "#86efac",
                    color: "#166534",
                    opacity: canSaveVisual && visualFields.dirty && !visualFields.saving ? 1 : 0.55,
                    cursor: canSaveVisual && visualFields.dirty && !visualFields.saving ? "pointer" : "not-allowed",
                  }}
                  disabled={!canSaveVisual || !visualFields.dirty || visualFields.saving}
                  onClick={() => p.scene_id && onSaveVisualFields?.(p.scene_id)}
                >
                  {visualFields.saving ? "Saving..." : "Save Visual Details"}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
