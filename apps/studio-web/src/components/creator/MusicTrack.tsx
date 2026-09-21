/**
 * MusicTrack — timeline surface showing background-music coverage and current
 * mix settings from the Timeline.
 *
 * Cue placement is a pure function of duration + pixel width (layoutMusic) on the
 * same px/second scale as the other tracks/playhead, so playback/seek stay
 * aligned. Coverage is derived (computeCoverage, clamped to [0, 1]) and mix
 * settings (independent music/narration volumes + muted) are displayed read-only
 * without mutating stored values. Audio elements are never given autoPlay, so no
 * sound starts before user interaction. Selection is controlled via selectedId +
 * onSelect (no internal selection state).
 */

// --------------- pure music model ---------------

export interface MusicCue {
  id: string;
  source: string | null;
  startSeconds: number;
  durationSeconds: number;
}

export interface MixSettings {
  musicVolume: number;
  narrationVolume: number;
  musicMuted: boolean;
}

export interface LaidMusic extends MusicCue {
  left: number;
  width: number;
}

/** Position music cues on the shared px/second scale. */
export function layoutMusic(
  cues: MusicCue[],
  durationSeconds: number,
  width: number,
): LaidMusic[] {
  if (durationSeconds <= 0) {
    return [];
  }
  const pxPerSecond = width / durationSeconds;
  return cues.map((cue) => ({
    ...cue,
    left: cue.startSeconds * pxPerSecond,
    width: cue.durationSeconds * pxPerSecond,
  }));
}

/**
 * Fraction of the timeline covered by music, in [0, 1]. Overlapping cues are
 * merged so coverage never exceeds the timeline (clamped at 1).
 */
export function computeCoverage(cues: MusicCue[], durationSeconds: number): number {
  if (durationSeconds <= 0 || cues.length === 0) {
    return 0;
  }
  const spans = cues
    .map((c) => [c.startSeconds, c.startSeconds + c.durationSeconds] as const)
    .sort((a, b) => a[0] - b[0]);
  let covered = 0;
  let curStart = spans[0][0];
  let curEnd = spans[0][1];
  for (let i = 1; i < spans.length; i += 1) {
    const [s, e] = spans[i];
    if (s <= curEnd) {
      curEnd = Math.max(curEnd, e);
    } else {
      covered += curEnd - curStart;
      curStart = s;
      curEnd = e;
    }
  }
  covered += curEnd - curStart;
  return Math.min(1, covered / durationSeconds);
}

/** Active music cue at ``t`` over half-open [start, end) windows; gaps -> null. */
export function musicAtTime(cues: MusicCue[], t: number): MusicCue | null {
  for (const cue of cues) {
    if (t >= cue.startSeconds && t < cue.startSeconds + cue.durationSeconds) {
      return cue;
    }
  }
  return null;
}

/** Human-readable mix summary: independent volumes + mute state. */
export function formatMix(mix: MixSettings): string {
  const music = `Music ${Math.round(mix.musicVolume * 100)}%`;
  const narration = `Narration ${Math.round(mix.narrationVolume * 100)}%`;
  const muted = mix.musicMuted ? " (muted)" : "";
  return `${music}${muted} · ${narration}`;
}

// --------------- component ---------------

export interface MusicTrackProps {
  cues: MusicCue[];
  durationSeconds: number;
  width: number;
  mix: MixSettings;
  selectedId?: string | null;
  currentTime?: number;
  onSelect?: (id: string) => void;
}

export default function MusicTrack({
  cues,
  durationSeconds,
  width,
  mix,
  selectedId = null,
  currentTime,
  onSelect,
}: MusicTrackProps) {
  const laid = layoutMusic(cues, durationSeconds, width);
  const coverage = computeCoverage(cues, durationSeconds);
  const activeId =
    currentTime === undefined ? null : (musicAtTime(cues, currentTime)?.id ?? null);

  return (
    <div
      data-testid="music-track"
      data-muted={mix.musicMuted ? "true" : "false"}
      style={{ position: "relative", width, minHeight: 44 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#9a9a9a" }}>
        <span data-testid="music-mix-settings">{formatMix(mix)}</span>
        <span data-testid="music-coverage">{Math.round(coverage * 100)}% covered</span>
      </div>
      <div style={{ position: "relative", width, height: 28, marginTop: 2 }}>
        {laid.map((cue) => {
          const selected = selectedId === cue.id;
          const active = activeId === cue.id;
          return (
            <div
              key={cue.id}
              data-testid={`music-cue-${cue.id}`}
              data-music-id={cue.id}
              data-selected={selected ? "true" : "false"}
              data-active={active ? "true" : "false"}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
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
                top: 0,
                height: "100%",
                boxSizing: "border-box",
                padding: "2px 4px",
                fontSize: 11,
                color: mix.musicMuted ? "#7a7a7a" : "#ccd8e0",
                background: active ? "#2e3543" : "#26292e",
                border: selected ? "2px solid #e5484d" : "1px solid #555",
                borderRadius: 4,
                cursor: "pointer",
                overflow: "hidden",
                whiteSpace: "nowrap",
                textOverflow: "ellipsis",
                opacity: mix.musicMuted ? 0.6 : 1,
              }}
            >
              {mix.musicMuted ? "🔇" : "🎵"} {cue.source ?? "missing"}
              {/* No autoPlay: preview audio must not sound before user interaction. */}
              {cue.source !== null && (
                <audio src={cue.source} preload="none" muted={mix.musicMuted} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
