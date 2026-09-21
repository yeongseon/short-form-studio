/**
 * VoiceTrack — timeline surface showing narration segments as the Voice track,
 * with derived silent-gap markers, preview-synchronized active highlighting, and
 * missing-media flagging.
 *
 * Placement is a pure function of duration + pixel width (layoutNarration) on the
 * same px/second scale as the other tracks/playhead. Silent gaps are DERIVED from
 * the segment timing (computeGaps), never stored, so the authoritative timing is
 * never mutated. The active segment at a time is a pure lookup (narrationAtTime)
 * over half-open [start, end) windows, so gaps yield no active segment. Selection
 * is controlled via selectedId + onSelect (no internal selection state). Segments
 * with a null source are flagged as missing media rather than dropped.
 */

// --------------- pure narration model ---------------

export interface NarrationSegment {
  id: string;
  source: string | null;
  startSeconds: number;
  durationSeconds: number;
}

export interface LaidNarration extends NarrationSegment {
  left: number;
  width: number;
}

export interface SilentGap {
  startSeconds: number;
  endSeconds: number;
}

/** Position narration segments on the shared px/second scale. */
export function layoutNarration(
  segments: NarrationSegment[],
  durationSeconds: number,
  width: number,
): LaidNarration[] {
  if (durationSeconds <= 0) {
    return [];
  }
  const pxPerSecond = width / durationSeconds;
  return segments.map((seg) => ({
    ...seg,
    left: seg.startSeconds * pxPerSecond,
    width: seg.durationSeconds * pxPerSecond,
  }));
}

/**
 * Derive silent gaps (uncovered spans) from ordered segments over [0, duration].
 * Purely computed from the authoritative timing — nothing is mutated or stored.
 */
export function computeGaps(
  segments: NarrationSegment[],
  durationSeconds: number,
): SilentGap[] {
  if (durationSeconds <= 0) {
    return [];
  }
  const ordered = [...segments].sort((a, b) => a.startSeconds - b.startSeconds);
  const gaps: SilentGap[] = [];
  let cursor = 0;
  for (const seg of ordered) {
    if (seg.startSeconds > cursor + 1e-9) {
      gaps.push({ startSeconds: cursor, endSeconds: seg.startSeconds });
    }
    cursor = Math.max(cursor, seg.startSeconds + seg.durationSeconds);
  }
  if (cursor + 1e-9 < durationSeconds) {
    gaps.push({ startSeconds: cursor, endSeconds: durationSeconds });
  }
  return gaps;
}

/** Active narration at ``t`` over half-open [start, end) windows; gaps -> null. */
export function narrationAtTime(
  segments: NarrationSegment[],
  t: number,
): NarrationSegment | null {
  for (const seg of segments) {
    if (t >= seg.startSeconds && t < seg.startSeconds + seg.durationSeconds) {
      return seg;
    }
  }
  return null;
}

// --------------- component ---------------

export interface VoiceTrackProps {
  segments: NarrationSegment[];
  durationSeconds: number;
  width: number;
  selectedId?: string | null;
  currentTime?: number;
  onSelect?: (id: string) => void;
}

export default function VoiceTrack({
  segments,
  durationSeconds,
  width,
  selectedId = null,
  currentTime,
  onSelect,
}: VoiceTrackProps) {
  const laid = layoutNarration(segments, durationSeconds, width);
  const gaps = computeGaps(segments, durationSeconds);
  const pxPerSecond = durationSeconds > 0 ? width / durationSeconds : 0;
  const activeId =
    currentTime === undefined ? null : (narrationAtTime(segments, currentTime)?.id ?? null);

  return (
    <div
      data-testid="voice-track"
      style={{ position: "relative", width, minHeight: 40 }}
    >
      {gaps.map((gap) => (
        <div
          key={`gap-${gap.startSeconds}`}
          data-gap={`${gap.startSeconds}-${gap.endSeconds}`}
          style={{
            position: "absolute",
            left: gap.startSeconds * pxPerSecond,
            width: (gap.endSeconds - gap.startSeconds) * pxPerSecond,
            top: 8,
            height: 4,
            background:
              "repeating-linear-gradient(90deg,#333 0 4px,transparent 4px 8px)",
            pointerEvents: "none",
          }}
        />
      ))}
      {laid.map((seg) => {
        const selected = selectedId === seg.id;
        const active = activeId === seg.id;
        const missing = seg.source === null;
        return (
          <div
            key={seg.id}
            data-testid={`voice-seg-${seg.id}`}
            data-narration-id={seg.id}
            data-selected={selected ? "true" : "false"}
            data-active={active ? "true" : "false"}
            data-missing={missing ? "true" : "false"}
            role="button"
            tabIndex={0}
            aria-pressed={selected}
            onClick={() => onSelect?.(seg.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect?.(seg.id);
              }
            }}
            style={{
              position: "absolute",
              left: seg.left,
              width: seg.width,
              top: 4,
              minHeight: 28,
              boxSizing: "border-box",
              padding: "2px 4px",
              fontSize: 11,
              color: missing ? "#e5a04d" : "#cfe0d6",
              background: active ? "#243b2e" : "#242a28",
              border: selected
                ? "2px solid #e5484d"
                : missing
                  ? "1px dashed #e5a04d"
                  : "1px solid #555",
              borderRadius: 4,
              cursor: "pointer",
              overflow: "hidden",
              whiteSpace: "nowrap",
              textOverflow: "ellipsis",
            }}
          >
            {missing ? "⚠ missing audio" : `🎙 ${seg.source}`}
          </div>
        );
      })}
    </div>
  );
}
