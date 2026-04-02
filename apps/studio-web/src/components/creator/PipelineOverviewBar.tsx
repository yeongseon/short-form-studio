/**
 * PipelineOverviewBar — compact sticky summary of pipeline progress + Render CTA.
 *
 * Shows: total scenes, per-type completion counts, progress bar, Render button.
 */

import type { StoryboardParagraph } from "../../api/storyboard";

// --------------- props ---------------

export interface PipelineOverviewBarProps {
  paragraphs: StoryboardParagraph[];
  totalParagraphs: number;
  readyParagraphs: number;
  renderReady: boolean;
  onRender?: () => void;
  /** True when render is in progress. */
  rendering?: boolean;
}

// --------------- styles ---------------

const barStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 16,
  padding: "10px 16px",
  background: "#fff",
  borderRadius: 8,
  border: "1px solid #e5e7eb",
  boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
  position: "sticky",
  top: 0,
  zIndex: 10,
};

const statStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 4,
  fontSize: 12,
  color: "#6b7280",
  whiteSpace: "nowrap",
};

const statValueStyle: React.CSSProperties = {
  fontWeight: 700,
  color: "#111827",
};

const progressOuter: React.CSSProperties = {
  flex: 1,
  height: 6,
  background: "#e5e7eb",
  borderRadius: 3,
  overflow: "hidden",
  minWidth: 60,
};

const renderBtnStyle: React.CSSProperties = {
  padding: "6px 16px",
  fontSize: 13,
  fontWeight: 700,
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  transition: "all 0.15s",
  whiteSpace: "nowrap",
};

// --------------- component ---------------

export default function PipelineOverviewBar({
  paragraphs,
  totalParagraphs,
  readyParagraphs,
  renderReady,
  onRender,
  rendering = false,
}: PipelineOverviewBarProps) {
  const imagesDone = paragraphs.filter((p) => p.image_url).length;
  const audioDone = paragraphs.filter((p) => p.audio_url).length;
  const subsDone = paragraphs.filter((p) => p.subtitles_url).length;
  const progress = totalParagraphs > 0 ? (readyParagraphs / totalParagraphs) * 100 : 0;

  return (
    <div style={barStyle} data-testid="pipeline-overview-bar">
      {/* Per-type stats */}
      <div style={statStyle} data-testid="stat-images">
        🖼️ <span style={statValueStyle}>{imagesDone}</span>/{totalParagraphs}
      </div>
      <div style={statStyle} data-testid="stat-audio">
        🔊 <span style={statValueStyle}>{audioDone}</span>/{totalParagraphs}
      </div>
      <div style={statStyle} data-testid="stat-subtitles">
        💬 <span style={statValueStyle}>{subsDone}</span>/{totalParagraphs}
      </div>

      {/* Progress bar */}
      <div style={progressOuter} data-testid="progress-bar">
        <div
          style={{
            height: "100%",
            width: `${progress}%`,
            background: renderReady ? "#22c55e" : "#4285f4",
            borderRadius: 3,
            transition: "width 0.3s ease",
          }}
        />
      </div>

      {/* Ready count */}
      <span style={{ fontSize: 12, color: "#6b7280", fontWeight: 600, whiteSpace: "nowrap" }}>
        {readyParagraphs}/{totalParagraphs} ready
      </span>

      {/* Render CTA */}
      <button
        type="button"
        style={{
          ...renderBtnStyle,
          background: renderReady && !rendering ? "#22c55e" : "#e5e7eb",
          color: renderReady && !rendering ? "#fff" : "#9ca3af",
          cursor: renderReady && !rendering ? "pointer" : "not-allowed",
        }}
        disabled={!renderReady || rendering}
        onClick={onRender}
        data-testid="render-btn"
      >
        {rendering ? "Rendering…" : "Render Video"}
      </button>
    </div>
  );
}
