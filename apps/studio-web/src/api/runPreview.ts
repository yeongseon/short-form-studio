import { API_BASE } from "./client";

export interface RenderedVideo {
  readonly id: number;
  readonly path: string;
  readonly render_profile: string | null;
  readonly created_at: string;
}

export interface RunPreview {
  readonly run_id: number;
  readonly current_stage: string;
  readonly video: RenderedVideo | null;
  readonly audio: { readonly id: number; readonly path: string; readonly model_used: string; readonly created_at: string } | null;
  readonly subtitle: { readonly id: number; readonly path: string; readonly format: string; readonly created_at: string } | null;
}

export function runArtifactUrl(runId: number, artifactId: number): string {
  return `${API_BASE}/runs/${runId}/artifacts/${artifactId}/download`;
}
