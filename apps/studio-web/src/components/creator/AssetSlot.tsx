/**
 * AssetSlot — reusable compact slot for image / audio / subtitle within a SceneCard.
 *
 * Three visual states:
 *   - empty: placeholder icon + label
 *   - loading: shimmer pulse animation
 *   - ready: content preview (thumbnail / play button / subtitle badge)
 *
 * Hover reveals a regenerate icon-button.
 */

import { useState, useRef } from "react";

// --------------- types ---------------

export type AssetType = "image" | "audio" | "subtitle";
export type AssetStatus = "empty" | "loading" | "ready";

export interface AssetSlotProps {
  type: AssetType;
  status: AssetStatus;
  /** URL of the asset when ready. */
  url?: string | null;
  /** Audio duration in seconds (audio type only). */
  duration?: number | null;
  /** Subtitle entry count (subtitle type only). */
  subtitleCount?: number | null;
  /** Called when asset doesn't exist yet and user clicks to generate. */
  onGenerate?: () => void;
  /** Called when the user clicks regenerate (asset already exists). */
  onRegenerate?: () => void;
  /** Called when the user clicks to preview the asset. */
  onPreview?: () => void;
  /** Whether interaction is disabled (e.g. during bulk generation). */
  disabled?: boolean;
}

// --------------- icons (inline SVG strings) ---------------

const ICONS: Record<AssetType, string> = {
  image: "🖼️",
  audio: "🔊",
  subtitle: "💬",
};

const LABELS: Record<AssetType, string> = {
  image: "Image",
  audio: "Audio",
  subtitle: "Subtitles",
};

// --------------- helpers ---------------

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}:${s.toString().padStart(2, "0")}` : `${s}s`;
}

/** Convert API artifact path → browser URL via Vite proxy. */
function artifactUrl(path: string): string {
  const match = path.match(/data\/artifacts\/(.*)/);
  return match ? `/artifacts/${match[1]}` : `/artifacts/${path}`;
}

// --------------- styles ---------------

const slotBase: React.CSSProperties = {
  position: "relative",
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "6px 10px",
  borderRadius: 6,
  border: "1px solid #e5e7eb",
  background: "#fff",
  minHeight: 36,
  cursor: "default",
  transition: "background 0.15s, border-color 0.15s",
  overflow: "hidden",
};

const emptyStyle: React.CSSProperties = {
  ...slotBase,
  background: "#f9fafb",
  borderStyle: "dashed",
};

const loadingStyle: React.CSSProperties = {
  ...slotBase,
  background: "linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%)",
  backgroundSize: "200% 100%",
  animation: "assetSlotShimmer 1.5s ease-in-out infinite",
};

const readyStyle: React.CSSProperties = {
  ...slotBase,
  background: "#f0fdf4",
  borderColor: "#bbf7d0",
};

const iconStyle: React.CSSProperties = {
  fontSize: 14,
  lineHeight: 1,
  flexShrink: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: "#6b7280",
  fontWeight: 500,
  flex: 1,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

const readyLabelStyle: React.CSSProperties = {
  ...labelStyle,
  color: "#166534",
  fontWeight: 600,
};

const regenBtnStyle: React.CSSProperties = {
  position: "absolute",
  right: 4,
  top: "50%",
  transform: "translateY(-50%)",
  width: 22,
  height: 22,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  borderRadius: 4,
  border: "1px solid #d1d5db",
  background: "#fff",
  cursor: "pointer",
  fontSize: 11,
  color: "#6b7280",
  opacity: 0,
  transition: "opacity 0.15s",
  padding: 0,
};

const thumbnailStyle: React.CSSProperties = {
  width: 32,
  height: 20,
  objectFit: "cover",
  borderRadius: 3,
  flexShrink: 0,
};

// --------------- keyframes (injected once) ---------------

let shimmerInjected = false;
function ensureShimmerKeyframes() {
  if (shimmerInjected || typeof document === "undefined") return;
  shimmerInjected = true;
  const style = document.createElement("style");
  style.textContent = `@keyframes assetSlotShimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`;
  document.head.appendChild(style);
}

// --------------- component ---------------

export default function AssetSlot({
  type,
  status,
  url,
  duration,
  subtitleCount,
  onGenerate,
  onRegenerate,
  onPreview,
  disabled = false,
}: AssetSlotProps) {
  ensureShimmerKeyframes();

  const [hovered, setHovered] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  const handleClick = () => {
    if (disabled) return;
    if (status !== "ready" || !url) return;

    if (type === "audio") {
      // Toggle inline play
      if (audioRef.current) {
        if (playing) {
          audioRef.current.pause();
          audioRef.current.currentTime = 0;
          setPlaying(false);
        } else {
          audioRef.current.play().catch(() => {});
          setPlaying(true);
        }
      }
      return;
    }

    onPreview?.();
  };

  const resolvedUrl = url ? artifactUrl(url) : null;

  // ---- empty ----
  if (status === "empty") {
    const canGenerate = Boolean(onGenerate) && !disabled;
    const content = (
      <>
        <span style={iconStyle}>{ICONS[type]}</span>
        <span
          style={{
            ...labelStyle,
            ...(canGenerate ? { color: "#1d4ed8", fontWeight: 600 } : {}),
          }}
        >
          {canGenerate ? `Generate ${LABELS[type]}` : LABELS[type]}
        </span>
      </>
    );

    if (canGenerate) {
      return (
        <button
          type="button"
          style={{
            ...emptyStyle,
            cursor: "pointer",
            ...(hovered ? { borderColor: "#93c5fd", background: "#eff6ff" } : {}),
            width: "100%",
            textAlign: "left",
            appearance: "none",
          }}
          data-testid={`asset-slot-${type}`}
          data-status="empty"
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onClick={onGenerate}
        >
          {content}
        </button>
      );
    }

    return (
      <div
        style={emptyStyle}
        data-testid={`asset-slot-${type}`}
        data-status="empty"
      >
        {content}
      </div>
    );
  }

  // ---- loading ----
  if (status === "loading") {
    return (
      <div
        style={loadingStyle}
        data-testid={`asset-slot-${type}`}
        data-status="loading"
      >
        <span style={iconStyle}>{ICONS[type]}</span>
        <span style={{ ...labelStyle, color: "#9ca3af" }}>Generating…</span>
      </div>
    );
  }

  // ---- ready ----
  const readyLabel = (() => {
    if (type === "audio" && duration != null) {
      return `${playing ? "▶ " : ""}${formatDuration(duration)}`;
    }
    if (type === "subtitle" && subtitleCount != null) {
      return `${subtitleCount} cue${subtitleCount !== 1 ? "s" : ""}`;
    }
    return "✓ Ready";
  })();
  const canPreview = !disabled && (type === "audio" || Boolean(onPreview));

  const readyContent = (
    <>
      {type === "image" && resolvedUrl && (
        <img
          src={resolvedUrl}
          alt="Scene thumbnail"
          style={thumbnailStyle}
        />
      )}

      {type !== "image" && <span style={iconStyle}>{ICONS[type]}</span>}

      <span style={readyLabelStyle}>{readyLabel}</span>

      {type === "audio" && resolvedUrl && (
        <audio
          ref={audioRef}
          src={resolvedUrl}
          preload="none"
          onEnded={() => setPlaying(false)}
          data-testid={`audio-element-${type}`}
        >
          <track kind="captions" />
        </audio>
      )}
    </>
  );

  const regenButton =
    onRegenerate && !disabled ? (
      <button
        type="button"
        style={{ ...regenBtnStyle, opacity: canPreview ? (hovered ? 1 : 0) : 1 }}
        onClick={(e) => {
          e.stopPropagation();
          onRegenerate();
        }}
        title={`Regenerate ${LABELS[type].toLowerCase()}`}
        data-testid={`regen-${type}`}
      >
        ↻
      </button>
    ) : null;

  if (canPreview) {
    return (
      <div
        style={{
          ...readyStyle,
          cursor: "pointer",
        }}
      >
        <button
          type="button"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            width: "100%",
            minHeight: 36,
            border: "none",
            background: "transparent",
            padding: 0,
            textAlign: "left",
            cursor: "pointer",
          }}
          data-testid={`asset-slot-${type}`}
          data-status="ready"
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => setHovered(false)}
          onClick={handleClick}
        >
          {readyContent}
        </button>
        {regenButton}
      </div>
    );
  }

  return (
    <div
      style={readyStyle}
      data-testid={`asset-slot-${type}`}
      data-status="ready"
    >
      {readyContent}
      {regenButton}
    </div>
  );
}
