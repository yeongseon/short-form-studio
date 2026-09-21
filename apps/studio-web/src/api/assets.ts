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
