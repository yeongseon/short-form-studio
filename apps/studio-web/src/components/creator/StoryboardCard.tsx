/**
 * StoryboardCard — single-paragraph card in the unified storyboard view.
 *
 * Displays: script text, image prompt, generated image preview, audio player,
 * subtitle preview, per-paragraph regenerate buttons, and status indicator.
 */

import type {
  StoryboardParagraph,
  ParagraphAudioParams,
  ParagraphSubtitlesParams,
} from "../../api/storyboard";

// --------------- helpers ---------------

/** Convert API artifact path → browser URL via Vite proxy. */
function artifactUrl(path: string): string {
  const match = path.match(/data\/artifacts\/(.*)/);
  return match ? `/artifacts/${match[1]}` : `/artifacts/${path}`;
}

const STATUS_COLORS: Record<string, { bg: string; border: string; text: string; label: string }> = {
  idle: { bg: "#f9fafb", border: "#e5e7eb", text: "#6b7280", label: "Idle" },
  generating_image: { bg: "#fdf4ff", border: "#e9d5ff", text: "#6b21a8", label: "Generating Image…" },
  generating_audio: { bg: "#fefce8", border: "#fde68a", text: "#92400e", label: "Generating Audio…" },
  generating_subtitles: { bg: "#f0f9ff", border: "#bae6fd", text: "#075985", label: "Generating Subtitles…" },
  ready: { bg: "#f0fdf4", border: "#bbf7d0", text: "#166534", label: "Ready" },
  stale: { bg: "#fffbeb", border: "#fde68a", text: "#b45309", label: "Stale" },
  failed: { bg: "#fef2f2", border: "#fca5a5", text: "#b91c1c", label: "Failed" },
};

// --------------- props ---------------

export interface StoryboardCardProps {
  paragraph: StoryboardParagraph;
  readOnly?: boolean;
  onGenerateAudio?: (sectionId: string, params: ParagraphAudioParams) => void;
  onGenerateSubtitles?: (sectionId: string, params: ParagraphSubtitlesParams) => void;
}

// --------------- styles ---------------

const cardStyle: React.CSSProperties = {
  border: "1px solid #e5e7eb",
  borderRadius: 10,
  background: "#fff",
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  padding: "10px 14px",
  borderBottom: "1px solid #f3f4f6",
  background: "#fafafa",
};

const bodyStyle: React.CSSProperties = {
  padding: 14,
  display: "flex",
  flexDirection: "column",
  gap: 12,
  flex: 1,
};

const sectionLabelStyle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 600,
  color: "#6b7280",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  marginBottom: 4,
};

const textBlockStyle: React.CSSProperties = {
  fontSize: 13,
  lineHeight: 1.5,
  color: "#374151",
  fontFamily: '"Inter", "Noto Sans KR", system-ui, sans-serif',
};

const promptStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#6b7280",
  fontStyle: "italic",
  lineHeight: 1.4,
  padding: "6px 10px",
  background: "#f9fafb",
  borderRadius: 4,
  border: "1px solid #f3f4f6",
};

const btnStyle: React.CSSProperties = {
  padding: "4px 10px",
  fontSize: 11,
  fontWeight: 500,
  border: "1px solid #d1d5db",
  borderRadius: 5,
  background: "#fff",
  cursor: "pointer",
  color: "#374151",
  transition: "all 0.15s",
};

const subtitlePreviewStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#6b7280",
  fontFamily: '"JetBrains Mono", "Fira Code", monospace',
  maxHeight: 100,
  overflowY: "auto",
  padding: "6px 10px",
  background: "#f9fafb",
  borderRadius: 4,
  border: "1px solid #f3f4f6",
  whiteSpace: "pre-wrap",
};

// --------------- component ---------------

export default function StoryboardCard({
  paragraph,
  readOnly = false,
  onGenerateAudio,
  onGenerateSubtitles,
}: StoryboardCardProps) {
  const p = paragraph;
  const statusInfo = STATUS_COLORS[p.status] ?? STATUS_COLORS.idle;
  const isGenerating = p.status.startsWith("generating_");

  return (
    <div style={cardStyle} data-testid={`storyboard-card-${p.section_id}`}>
      {/* Header — order + status */}
      <div style={headerStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#111827" }}>
            §{p.order + 1}
          </span>
          <span style={{ fontSize: 11, color: "#9ca3af" }}>{p.section_id}</span>
        </div>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "2px 8px",
            borderRadius: 10,
            background: statusInfo.bg,
            border: `1px solid ${statusInfo.border}`,
            color: statusInfo.text,
          }}
        >
          {statusInfo.label}
        </span>
      </div>

      {/* Body */}
      <div style={bodyStyle}>
        {/* Script text */}
        <div>
          <div style={sectionLabelStyle}>Script</div>
          <div style={textBlockStyle}>
            {p.display_text ?? p.text}
          </div>
        </div>

        {/* Image prompt */}
        {p.image_prompt && (
          <div>
            <div style={sectionLabelStyle}>Image Prompt</div>
            <div style={promptStyle}>{p.image_prompt}</div>
          </div>
        )}

        {/* Image preview */}
        {p.image_url && (
          <div>
            <div style={sectionLabelStyle}>Image</div>
            <img
              src={artifactUrl(p.image_url)}
              alt={`Scene for §${p.order + 1}`}
              style={{
                width: "100%",
                maxHeight: 220,
                objectFit: "contain",
                borderRadius: 6,
                background: "#f3f4f6",
                display: "block",
              }}
            />
          </div>
        )}

        {/* Audio player */}
        {p.audio_url && (
          <div>
            <div style={sectionLabelStyle}>
              Audio
              {p.audio_duration != null && (
                <span style={{ fontWeight: 400, fontSize: 11, color: "#9ca3af", marginLeft: 6 }}>
                  {p.audio_duration.toFixed(1)}s
                </span>
              )}
            </div>
            <audio
              controls
              style={{ width: "100%", height: 32, borderRadius: 4 }}
              src={artifactUrl(p.audio_url)}
            />
          </div>
        )}

        {/* Subtitle preview */}
        {p.subtitle_entries && p.subtitle_entries.length > 0 && (
          <div>
            <div style={sectionLabelStyle}>
              Subtitles ({p.subtitle_entries.length})
            </div>
            <div style={subtitlePreviewStyle}>
              {p.subtitle_entries.map((e, i) => (
                <div key={i}>
                  <span style={{ color: "#9ca3af" }}>{e.start} → {e.end}</span>{" "}
                  {e.text}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Stale flags */}
        {p.stale_flags && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {p.stale_flags.prompt_stale && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "#fef3c7", color: "#b45309" }}>
                Prompt stale
              </span>
            )}
            {p.stale_flags.image_stale && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "#fef3c7", color: "#b45309" }}>
                Image stale
              </span>
            )}
            {p.stale_flags.audio_stale && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "#fef3c7", color: "#b45309" }}>
                Audio stale
              </span>
            )}
            {p.stale_flags.subtitles_stale && (
              <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 3, background: "#fef3c7", color: "#b45309" }}>
                Subtitles stale
              </span>
            )}
          </div>
        )}

        {/* Action buttons */}
        {!readOnly && !isGenerating && (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {/* Generate Audio button */}
            {!p.audio_url && p.image_url && (
              <button
                type="button"
                style={{ ...btnStyle, borderColor: "#fde68a", background: "#fffbeb", color: "#92400e" }}
                onClick={() => onGenerateAudio?.(p.section_id, {})}
                data-testid={`gen-audio-${p.section_id}`}
              >
                Generate Audio
              </button>
            )}
            {/* Regenerate Audio button */}
            {p.audio_url && (
              <button
                type="button"
                style={btnStyle}
                onClick={() => onGenerateAudio?.(p.section_id, {})}
                data-testid={`regen-audio-${p.section_id}`}
              >
                Regen Audio
              </button>
            )}
            {/* Generate Subtitles button — only when audio exists */}
            {p.audio_url && !p.subtitles_url && (
              <button
                type="button"
                style={{ ...btnStyle, borderColor: "#bae6fd", background: "#f0f9ff", color: "#075985" }}
                onClick={() => onGenerateSubtitles?.(p.section_id, {})}
                data-testid={`gen-subs-${p.section_id}`}
              >
                Generate Subtitles
              </button>
            )}
            {/* Regenerate Subtitles button */}
            {p.subtitles_url && (
              <button
                type="button"
                style={btnStyle}
                onClick={() => onGenerateSubtitles?.(p.section_id, {})}
                data-testid={`regen-subs-${p.section_id}`}
              >
                Regen Subtitles
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
