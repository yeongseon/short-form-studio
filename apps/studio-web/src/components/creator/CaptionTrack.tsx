/**
 * CaptionTrack — timeline surface showing timed caption cues at their Timeline
 * positions, with controlled selection and preview-synchronized active
 * highlighting.
 *
 * Cue placement is a pure function of duration + pixel width (layoutCaptions)
 * using the same time scale as the ruler/playhead/visual track, so a cue aligns
 * with the playhead at its start time. The active cue at a given time is a pure
 * lookup (captionAtTime) over half-open [start, end) windows, so gaps yield no
 * active cue and the end boundary is exclusive. Selection is controlled via
 * selectedId + onSelect (no internal selection state). Caption text carries its
 * own text (Track TEXT/CAPTION role) — no image assets — and wraps rather than
 * clips so long and CJK strings stay fully visible.
 */

// --------------- pure caption model ---------------

export interface CaptionCue {
  id: string;
  text: string;
  startSeconds: number;
  endSeconds: number;
}

export interface LaidCaption extends CaptionCue {
  left: number;
  width: number;
}

/** Position cues on a pixel width using the shared px/second time scale. */
export function layoutCaptions(
  cues: CaptionCue[],
  durationSeconds: number,
  width: number,
): LaidCaption[] {
  if (durationSeconds <= 0) {
    return [];
  }
  const pxPerSecond = width / durationSeconds;
  return cues.map((cue) => ({
    ...cue,
    left: cue.startSeconds * pxPerSecond,
    width: (cue.endSeconds - cue.startSeconds) * pxPerSecond,
  }));
}

/**
 * The active cue at time ``t`` over half-open [start, end) windows. Gaps return
 * null and the end boundary is exclusive, so a cue never lingers past its end.
 */
export function captionAtTime(cues: CaptionCue[], t: number): CaptionCue | null {
  for (const cue of cues) {
    if (t >= cue.startSeconds && t < cue.endSeconds) {
      return cue;
    }
  }
  return null;
}

// --------------- component ---------------

export interface CaptionTrackProps {
  cues: CaptionCue[];
  durationSeconds: number;
  width: number;
  selectedId?: string | null;
  currentTime?: number;
  onSelect?: (id: string) => void;
}

export default function CaptionTrack({
  cues,
  durationSeconds,
  width,
  selectedId = null,
  currentTime,
  onSelect,
}: CaptionTrackProps) {
  const laid = layoutCaptions(cues, durationSeconds, width);
  const activeId =
    currentTime === undefined ? null : (captionAtTime(cues, currentTime)?.id ?? null);

  return (
    <div
      data-testid="caption-track"
      style={{ position: "relative", width, minHeight: 40 }}
    >
      {laid.map((cue) => {
        const selected = selectedId === cue.id;
        const active = activeId === cue.id;
        return (
          <div
            key={cue.id}
            data-testid={`caption-cue-${cue.id}`}
            data-cue-id={cue.id}
            data-selected={selected ? "true" : "false"}
            data-active={active ? "true" : "false"}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            title={cue.text}
            onClick={() => onSelect?.(cue.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect?.(cue.id);
              }
            }}
            style={{
              position: "absolute",
              left: cue.left,
              width: cue.width,
              top: 4,
              minHeight: 28,
              padding: "2px 4px",
              boxSizing: "border-box",
              background: active ? "#243b2e" : "#2a2a2a",
              border: selected ? "2px solid #e5484d" : "1px solid #555",
              borderRadius: 4,
              color: "#dcdcdc",
              fontSize: 11,
              lineHeight: 1.3,
              cursor: "pointer",
              // Long/CJK text must wrap, never clip.
              whiteSpace: "normal",
              overflowWrap: "break-word",
              wordBreak: "break-word",
            }}
          >
            {cue.text}
          </div>
        );
      })}
    </div>
  );
}
