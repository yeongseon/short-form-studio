/**
 * Timeline preview API client — fetches the compiled RenderPlan that the
 * renderer also consumes, so the browser preview and the final render share
 * one source. Mirrors backend models in creator_domain.models.render_plan.
 */
import { apiJson, API_BASE } from "./client";

// --------------- types ---------------

export type RenderSegmentKind = "image" | "video";

export interface RenderSegment {
  kind: RenderSegmentKind;
  source: string;
  timeline_start_seconds: number;
  duration_seconds: number;
  trim_start_seconds: number | null;
  trim_end_seconds: number | null;
  fit_mode: string;
  transition: string | null;
}

export interface OutputSpec {
  width: number;
  height: number;
  fps: number;
}

export interface EncodingProfile {
  name: string;
  video_codec: string;
  audio_codec: string;
  crf: number;
  preset: string;
}

export interface RenderPlan {
  segments: RenderSegment[];
  output_spec: OutputSpec;
  encoding_profile: EncodingProfile;
  narration_path: string | null;
  subtitle_path: string | null;
  music_path: string | null;
}

export interface TimelinePreviewOptions {
  output?: string;
  encoding?: string;
}

// --------------- API functions ---------------

/**
 * Fetch the compiled RenderPlan preview for a project's saved Timeline.
 * Throws ApiError (with status + detail) on 404 (no timeline / cross-tenant)
 * or 400 (unknown preset / unavailable media).
 */
export async function fetchTimelinePreview(
  projectId: number,
  opts: TimelinePreviewOptions = {},
): Promise<RenderPlan> {
  const params = new URLSearchParams({
    output: opts.output ?? "short_vertical",
    encoding: opts.encoding ?? "preview",
  });
  return apiJson<RenderPlan>(
    `${API_BASE}/projects/${projectId}/timeline/preview?${params.toString()}`,
  );
}
