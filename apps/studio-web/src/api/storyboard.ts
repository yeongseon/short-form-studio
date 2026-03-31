/**
 * Storyboard API client — TypeScript types and fetch functions
 * for the unified paragraph-based pipeline.
 *
 * Mirrors backend models in creator_domain.models.storyboard.
 */

const API_BASE = "/api/creator";

// --------------- types ---------------

export type ParagraphStatus =
  | "idle"
  | "generating_image"
  | "generating_audio"
  | "generating_subtitles"
  | "ready"
  | "stale"
  | "failed";

export interface StaleFlags {
  prompt_stale: boolean;
  image_stale: boolean;
  audio_stale: boolean;
  subtitles_stale: boolean;
}

export interface SubtitleEntry {
  index: number;
  start: string;
  end: string;
  text: string;
}

export interface StoryboardParagraph {
  section_id: string;
  order: number;
  text: string;
  display_text: string | null;
  image_prompt: string | null;
  image_url: string | null;
  audio_url: string | null;
  audio_duration: number | null;
  subtitles_url: string | null;
  subtitle_entries: SubtitleEntry[] | null;
  status: ParagraphStatus;
  stale_flags: StaleFlags | null;
  scene_id: string | null;
  image_asset_id: number | null;
  audio_artifact_id: number | null;
  subtitle_artifact_id: number | null;
}

export interface StoryboardResponse {
  run_id: number;
  paragraphs: StoryboardParagraph[];
  render_ready: boolean;
  total_paragraphs: number;
  ready_paragraphs: number;
}

export interface ParagraphAudioParams {
  tts_model?: string;
  voice?: string;
}

export interface ParagraphSubtitlesParams {
  subtitle_model?: string;
  subtitle_format?: string;
}

// --------------- API functions ---------------

/**
 * Fetch full storyboard for a run — assembles paragraphs from
 * script sections + visual plan + images + audio + subtitles.
 */
export async function fetchStoryboard(runId: number): Promise<StoryboardResponse> {
  const res = await fetch(`${API_BASE}/runs/${runId}/storyboard`);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Failed to fetch storyboard (${res.status})`);
  }
  return res.json();
}

/**
 * Generate audio for a single paragraph (section).
 */
export async function generateParagraphAudio(
  runId: number,
  sectionId: string,
  params: ParagraphAudioParams = {},
): Promise<{ task_id: string }> {
  const res = await fetch(
    `${API_BASE}/runs/${runId}/storyboard/paragraphs/${sectionId}/generate-audio`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tts_model: params.tts_model ?? "qwen3-tts",
        voice: params.voice ?? "default",
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Generate audio failed (${res.status})`);
  }
  return res.json();
}

/**
 * Generate subtitles for a single paragraph (section).
 * Requires audio to already exist for this paragraph.
 */
export async function generateParagraphSubtitles(
  runId: number,
  sectionId: string,
  params: ParagraphSubtitlesParams = {},
): Promise<{ task_id: string }> {
  const res = await fetch(
    `${API_BASE}/runs/${runId}/storyboard/paragraphs/${sectionId}/generate-subtitles`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subtitle_model: params.subtitle_model ?? "whisper-small",
        subtitle_format: params.subtitle_format ?? "srt",
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Generate subtitles failed (${res.status})`);
  }
  return res.json();
}

/**
 * Generate audio for ALL paragraphs in bulk.
 */
export async function generateAllParagraphAudio(
  runId: number,
  params: ParagraphAudioParams = {},
): Promise<{ dispatched: number }> {
  const res = await fetch(
    `${API_BASE}/runs/${runId}/storyboard/generate-all-audio`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tts_model: params.tts_model ?? "qwen3-tts",
        voice: params.voice ?? "default",
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Bulk audio generation failed (${res.status})`);
  }
  return res.json();
}

/**
 * Generate subtitles for ALL paragraphs that have audio.
 */
export async function generateAllParagraphSubtitles(
  runId: number,
  params: ParagraphSubtitlesParams = {},
): Promise<{ dispatched: number }> {
  const res = await fetch(
    `${API_BASE}/runs/${runId}/storyboard/generate-all-subtitles`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subtitle_model: params.subtitle_model ?? "whisper-small",
        subtitle_format: params.subtitle_format ?? "srt",
      }),
    },
  );
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Bulk subtitle generation failed (${res.status})`);
  }
  return res.json();
}
