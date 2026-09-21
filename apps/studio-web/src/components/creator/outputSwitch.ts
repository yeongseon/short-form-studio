/**
 * outputSwitch — pure model for switching the output aspect-ratio preset without
 * resetting Timeline edits or encoding quality, with explicit fitting rules and
 * reversible undo/redo.
 *
 * switchOutput changes ONLY the output geometry (width/height/fps) to a named
 * short preset; it preserves the segments (ids, durations, asset references) and
 * the encoding profile untouched. Fitting is applied explicitly per segment via
 * fitModeFor: switching to a different aspect promotes a cropping "cover" to
 * "contain" so no edited content is silently cropped, while an explicit
 * "contain" is kept and a same-aspect switch leaves fit unchanged.
 * applyOutputSwitch performs the change atomically over an OutputHistory so undo
 * reverses the output change without losing edits (the change is reversible).
 */

export const OUTPUT_PRESETS = [
  "short_vertical",
  "short_square",
  "short_landscape",
] as const;

export type OutputPresetName = (typeof OUTPUT_PRESETS)[number];

export interface OutputSpec {
  width: number;
  height: number;
  fps: number;
  preset: OutputPresetName;
}

export interface EncodingProfile {
  name: string;
  crf: number;
  preset: string;
}

export type FitMode = "cover" | "contain";

export interface OutputSegment {
  id: string;
  assetId: number;
  durationSeconds: number;
  fitMode: FitMode;
}

export interface OutputProject {
  output: OutputSpec;
  encoding: EncodingProfile;
  segments: OutputSegment[];
}

export interface OutputHistory {
  past: OutputProject[];
  present: OutputProject;
  future: OutputProject[];
  canUndo: boolean;
  canRedo: boolean;
}

const _PRESET_DIMENSIONS: Record<OutputPresetName, { width: number; height: number }> = {
  short_vertical: { width: 1080, height: 1920 },
  short_square: { width: 1080, height: 1080 },
  short_landscape: { width: 1920, height: 1080 },
};

/** Resolve a named short output preset to its geometry. Throws on an unknown name. */
export function outputPreset(name: string): OutputSpec {
  const dims = _PRESET_DIMENSIONS[name as OutputPresetName];
  if (dims === undefined) {
    throw new Error(`unknown output preset: ${name}`);
  }
  return { width: dims.width, height: dims.height, fps: 30, preset: name as OutputPresetName };
}

function aspectOf(preset: OutputPresetName): number {
  const dims = _PRESET_DIMENSIONS[preset];
  return dims.width / dims.height;
}

/**
 * Explicit fitting rule across an aspect change: a same-aspect switch keeps the
 * current fit; an aspect change promotes a cropping "cover" to "contain" so
 * edited content is not silently cropped; an explicit "contain" is preserved.
 */
export function fitModeFor(
  current: FitMode,
  fromPreset: OutputPresetName,
  toPreset: OutputPresetName,
): FitMode {
  if (aspectOf(fromPreset) === aspectOf(toPreset)) {
    return current;
  }
  return current === "cover" ? "contain" : current;
}

/**
 * Switch the project's output to ``toPresetName`` (geometry only), preserving
 * segments and encoding and applying the explicit fitting rule per segment.
 * Throws on an unknown preset.
 */
export function switchOutput(
  project: OutputProject,
  toPresetName: string,
): OutputProject {
  const output = outputPreset(toPresetName);
  const from = project.output.preset;
  return {
    ...project,
    output,
    segments: project.segments.map((segment) => ({
      ...segment,
      fitMode: fitModeFor(segment.fitMode, from, output.preset),
    })),
  };
}

export function createOutputHistory(project: OutputProject): OutputHistory {
  return { past: [], present: project, future: [], canUndo: false, canRedo: false };
}

export function applyOutputSwitch(
  history: OutputHistory,
  toPresetName: string,
): OutputHistory {
  const present = switchOutput(history.present, toPresetName);
  return {
    past: [...history.past, history.present],
    present,
    future: [],
    canUndo: true,
    canRedo: false,
  };
}

export function undo(history: OutputHistory): OutputHistory {
  if (history.past.length === 0) {
    return history;
  }
  const previous = history.past[history.past.length - 1];
  const past = history.past.slice(0, -1);
  return {
    past,
    present: previous,
    future: [history.present, ...history.future],
    canUndo: past.length > 0,
    canRedo: true,
  };
}

export function redo(history: OutputHistory): OutputHistory {
  if (history.future.length === 0) {
    return history;
  }
  const next = history.future[0];
  const future = history.future.slice(1);
  return {
    past: [...history.past, history.present],
    present: next,
    future,
    canUndo: true,
    canRedo: future.length > 0,
  };
}
