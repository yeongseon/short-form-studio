/**
 * SceneCardGrid — displays ALL scene cards in a responsive grid.
 *
 * All scenes visible at once — no pagination, no virtual scroll.
 * Compact cards fit 5-10+ scenes on a typical 1080p screen.
 */

import SceneCard from "./SceneCard";
import type { StoryboardParagraph } from "../../api/storyboard";

// --------------- props ---------------

export interface SceneCardGridProps {
  paragraphs: StoryboardParagraph[];
  onGenerateImage?: (sceneId: string) => void;
  onGenerateAudio?: (sectionId: string) => void;
  onGenerateSubtitles?: (sectionId: string) => void;
  /** Disable all per-scene actions. */
  disabled?: boolean;
}

// --------------- styles ---------------

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
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
    <div style={gridStyle} data-testid="scene-card-grid">
      {paragraphs.map((p) => (
        <SceneCard
          key={p.section_id}
          paragraph={p}
          onGenerateImage={onGenerateImage}
          onGenerateAudio={onGenerateAudio}
          onGenerateSubtitles={onGenerateSubtitles}
          disabled={disabled}
        />
      ))}
    </div>
  );
}
