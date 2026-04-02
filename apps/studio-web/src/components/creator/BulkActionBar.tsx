/**
 * BulkActionBar — batch operation buttons with remaining counts.
 *
 * "Generate All Images (4 remaining)", "Generate All Audio (6 remaining)", etc.
 * Buttons disabled when all complete or generation in progress.
 */

import type { StoryboardParagraph } from "../../api/storyboard";

// --------------- props ---------------

export interface BulkActionBarProps {
  paragraphs: StoryboardParagraph[];
  /** True when any bulk or per-scene generation is in progress. */
  generating?: boolean;
  onGenerateAllImages?: () => void;
  onGenerateAllAudio?: () => void;
  onGenerateAllSubtitles?: () => void;
}

// --------------- styles ---------------

const barStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "8px 12px",
  background: "#fafafa",
  borderRadius: 8,
  border: "1px solid #e5e7eb",
  flexWrap: "wrap",
};

const btnBase: React.CSSProperties = {
  padding: "5px 12px",
  fontSize: 12,
  fontWeight: 600,
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#fff",
  cursor: "pointer",
  color: "#374151",
  transition: "all 0.15s",
  whiteSpace: "nowrap",
};

const disabledBtn: React.CSSProperties = {
  ...btnBase,
  opacity: 0.5,
  cursor: "not-allowed",
};

// --------------- component ---------------

export default function BulkActionBar({
  paragraphs,
  generating = false,
  onGenerateAllImages,
  onGenerateAllAudio,
  onGenerateAllSubtitles,
}: BulkActionBarProps) {
  const total = paragraphs.length;
  if (total === 0) return null;

  const imagesRemaining = paragraphs.filter((p) => !p.image_url).length;
  const audioRemaining = paragraphs.filter((p) => !p.audio_url).length;
  const subtitlesRemaining = paragraphs.filter((p) => !p.subtitles_url).length;
  const hasAnyGenerating = paragraphs.some((p) => p.status.startsWith("generating_"));
  const isDisabled = generating || hasAnyGenerating;

  return (
    <div style={barStyle} data-testid="bulk-action-bar">
      {/* Generate All Images */}
      <button
        type="button"
        style={{
          ...(isDisabled || imagesRemaining === 0 ? disabledBtn : btnBase),
          borderColor: "#e9d5ff",
          color: isDisabled || imagesRemaining === 0 ? "#9ca3af" : "#6b21a8",
        }}
        disabled={isDisabled || imagesRemaining === 0}
        onClick={onGenerateAllImages}
        data-testid="bulk-gen-images"
      >
        {imagesRemaining > 0
          ? `Generate All Images (${imagesRemaining})`
          : `All Images Done ✓`}
      </button>

      {/* Generate All Audio */}
      <button
        type="button"
        style={{
          ...(isDisabled || audioRemaining === 0 ? disabledBtn : btnBase),
          borderColor: "#fde68a",
          color: isDisabled || audioRemaining === 0 ? "#9ca3af" : "#92400e",
        }}
        disabled={isDisabled || audioRemaining === 0}
        onClick={onGenerateAllAudio}
        data-testid="bulk-gen-audio"
      >
        {audioRemaining > 0
          ? `Generate All Audio (${audioRemaining})`
          : `All Audio Done ✓`}
      </button>

      {/* Generate All Subtitles */}
      <button
        type="button"
        style={{
          ...(isDisabled || subtitlesRemaining === 0 ? disabledBtn : btnBase),
          borderColor: "#bae6fd",
          color: isDisabled || subtitlesRemaining === 0 ? "#9ca3af" : "#075985",
        }}
        disabled={isDisabled || subtitlesRemaining === 0}
        onClick={onGenerateAllSubtitles}
        data-testid="bulk-gen-subtitles"
      >
        {subtitlesRemaining > 0
          ? `Generate All Subtitles (${subtitlesRemaining})`
          : `All Subtitles Done ✓`}
      </button>
    </div>
  );
}
