/**
 * Timeline persistence API client — revision-aware save used by Autosave.
 *
 * PUT carries the expected revision so the server rejects a stale write (409),
 * and the caller (Autosave) maps that to a conflict state rather than silently
 * overwriting a concurrent change.
 */
import { apiJson, ApiError, API_BASE } from "./client";
import type { SaveResult } from "../components/creator/autosave";

export interface SavedTimeline {
  id: string;
  project_id: number;
  revision: number;
  segments: unknown[];
}

/**
 * Persist a timeline for a project with an optimistic revision check. Returns a
 * discriminated SaveResult so callers handle conflict (409) distinctly from
 * other errors without try/catch at the call site.
 */
export async function saveTimeline(
  projectId: number,
  timeline: SavedTimeline,
  expectedRevision: number,
): Promise<SaveResult<SavedTimeline>> {
  try {
    const saved = await apiJson<SavedTimeline>(
      `${API_BASE}/projects/${projectId}/timeline`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: expectedRevision, timeline }),
      },
    );
    return { ok: true, timeline: saved };
  } catch (err: unknown) {
    if (err instanceof ApiError && err.status === 409) {
      return { ok: false, kind: "conflict", message: err.detail };
    }
    const message = err instanceof Error ? err.message : "save failed";
    return { ok: false, kind: "error", message };
  }
}
