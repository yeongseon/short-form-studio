import { API_BASE } from "./client";
import { runArtifactUrl } from "./runPreview";
import type { StoryboardParagraph } from "./storyboard";
import type { MediaAsset } from "./assets";

export function visualAssetUrl(runId: number, assetId: number): string {
  return `${API_BASE}/runs/${runId}/visual-assets/${assetId}/content`;
}

export function workspaceAssetUrl(asset: MediaAsset): string {
  return asset.project_id === null
    ? `${API_BASE}/workspaces/${asset.workspace_id}/assets/${asset.id}/content`
    : `${API_BASE}/projects/${asset.project_id}/assets/${asset.id}/content`;
}

export function storyboardMediaUrls(runId: number, paragraph: StoryboardParagraph): StoryboardParagraph {
  return {
    ...paragraph,
    image_url: paragraph.image_asset_id === null ? null : visualAssetUrl(runId, paragraph.image_asset_id),
    audio_url: paragraph.audio_artifact_id === null ? null : runArtifactUrl(runId, paragraph.audio_artifact_id),
    subtitles_url: paragraph.subtitle_artifact_id === null ? null : runArtifactUrl(runId, paragraph.subtitle_artifact_id),
  };
}
