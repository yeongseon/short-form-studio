/**
 * SceneCardGrid — displays ALL scene cards in a vertical list.
 *
 * Full-width horizontal cards, one per row.
 * All scenes visible at once — no pagination, no virtual scroll.
 */

import SceneCard from "./SceneCard";
import type { StoryboardParagraph } from "../../api/storyboard";

// --------------- props ---------------

export interface SceneCardGridProps {
  paragraphs: StoryboardParagraph[];
  currentStage: string;
  visualFieldBySceneId?: Record<string, {
    prompt: string;
    mood: string | null;
    composition: string | null;
    style_tags: string[];
    prompt_source: "auto_generated" | "user_edited" | "model_suggested";
    generation_status: "pending" | "generating" | "completed" | "failed";
    dirty?: boolean;
    saving?: boolean;
  }>;
  onVisualFieldChange?: (
    sceneId: string,
    field: "prompt" | "mood" | "composition" | "style_tags",
    value: string,
  ) => void;
  onSaveVisualFields?: (sceneId: string) => void;
  onGenerateImage?: (sceneId: string) => void;
  onGenerateAudio?: (sectionId: string) => void;
  onGenerateSubtitles?: (sectionId: string) => void;
  /** Disable all per-scene actions. */
  disabled?: boolean;
}

// --------------- styles ---------------

const listStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const emptyStyle: React.CSSProperties = {
  textAlign: "center",
  padding: 32,
  color: "#6b7280",
  fontSize: 13,
  background: "#f9fafb",
  borderRadius: 8,
  border: "1px dashed #d1d5db",
};

// --------------- component ---------------

export default function SceneCardGrid({
  paragraphs,
  currentStage,
  visualFieldBySceneId,
  onVisualFieldChange,
  onSaveVisualFields,
  onGenerateImage,
  onGenerateAudio,
  onGenerateSubtitles,
  disabled = false,
}: SceneCardGridProps) {
  if (paragraphs.length === 0) {
    return (
      <div style={emptyStyle} data-testid="scene-card-grid-empty">
        No scenes in storyboard. Generate a script and visual plan first.
      </div>
    );
  }

  return (
    <div style={listStyle} data-testid="scene-card-grid">
      {paragraphs.map((p) => (
        <SceneCard
          key={p.section_id}
          paragraph={p}
          currentStage={currentStage}
          visualFields={p.scene_id ? visualFieldBySceneId?.[p.scene_id] : undefined}
          onVisualFieldChange={onVisualFieldChange}
          onSaveVisualFields={onSaveVisualFields}
          onGenerateImage={onGenerateImage}
          onGenerateAudio={onGenerateAudio}
          onGenerateSubtitles={onGenerateSubtitles}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
