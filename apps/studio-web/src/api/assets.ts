/**
 * Asset Library API client — workspace-scoped uploaded/generated media assets.
 * Mirrors backend creator_domain.models.media_asset. The backend derives the
 * workspace from auth, so the browser never passes another workspace's id.
 */
import { apiJson, API_BASE } from "./client";

// --------------- types ---------------

export type MediaType = "IMAGE" | "VIDEO" | "AUDIO" | "LOGO" | "GRAPHIC";
export type MediaOrigin =
  | "GENERATED"
  | "UPLOADED"
  | "EXTERNAL_URL"
  | "STOCK"
  | "IMPORTED";

export interface MediaAsset {
  id: number;
  workspace_id: number;
  project_id: number | null;
  run_id: number | null;
  media_type: MediaType;
  origin: MediaOrigin;
  storage_key: string | null;
  mime_type: string | null;
  width: number | null;
  height: number | null;
  duration_seconds: number | null;
  source_url: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AssetPage {
  items: MediaAsset[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListAssetsOptions {
  mediaType?: MediaType;
  projectId?: number;
  limit?: number;
  offset?: number;
}

// --------------- API functions ---------------

/**
 * List the caller's workspace assets, uploaded-origin first. The path
 * workspace id is required by the route but the backend scopes to the
 * authenticated workspace, so cross-workspace assets are never returned.
 */
export async function listWorkspaceAssets(
  workspaceId: number,
  opts: ListAssetsOptions = {},
): Promise<AssetPage> {
  const params = new URLSearchParams();
  if (opts.mediaType) {
    params.set("media_type", opts.mediaType);
  }
  if (opts.projectId !== undefined) {
    params.set("project_id", String(opts.projectId));
  }
  params.set("limit", String(opts.limit ?? 50));
  params.set("offset", String(opts.offset ?? 0));
  return apiJson<AssetPage>(
    `${API_BASE}/workspaces/${workspaceId}/assets?${params.toString()}`,
  );
}

/** The three upload kinds map to distinct backend routes. */
export type UploadKind = "image" | "video" | "audio";

const _UPLOAD_PATH: Record<UploadKind, string> = {
  image: "assets",
  video: "assets/videos",
  audio: "assets/audio",
};

/** Classify a File by its MIME type into an upload kind, or null if unsupported. */
export function uploadKindForFile(file: File): UploadKind | null {
  if (file.type.startsWith("image/")) {
    return "image";
  }
  if (file.type.startsWith("video/")) {
    return "video";
  }
  if (file.type.startsWith("audio/")) {
    return "audio";
  }
  return null;
}

/**
 * Upload a file to the caller's workspace via the validated upload API. Routes
 * to the image/video/audio endpoint by ``kind``; the backend re-validates and
 * probes the content, so an unsupported or oversized file is rejected there.
 */
export async function uploadAsset(
  workspaceId: number,
  kind: UploadKind,
  file: File,
): Promise<MediaAsset> {
  const form = new FormData();
  form.append("file", file);
  return apiJson<MediaAsset>(
    `${API_BASE}/workspaces/${workspaceId}/${_UPLOAD_PATH[kind]}`,
    { method: "POST", body: form },
  );
}
