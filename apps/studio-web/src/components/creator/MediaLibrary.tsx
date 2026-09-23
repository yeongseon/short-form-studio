/**
 * MediaLibrary — editor media library for the caller's workspace assets.
 *
 * Fetches workspace-scoped assets (the backend derives the workspace from auth,
 * so no other workspace's assets are ever requested or shown) and presents
 * uploaded / generated / brand views. Brand collects stock, imported, and
 * external-url origins. Assets are shown in the backend's uploaded-first order
 * (never re-sorted), with metadata + a preview, and loading / empty / error /
 * ready states via data-status. Selection is controlled (selectedId + onSelect).
 */

import { useEffect, useRef, useState } from "react";

import { listWorkspaceAssets } from "../../api/assets";
import type { MediaAsset, MediaOrigin } from "../../api/assets";
import { workspaceAssetUrl } from "../../api/mediaUrls";

export type { MediaAsset } from "../../api/assets";

type LibraryView = "all" | "uploaded" | "generated" | "brand";

export interface ViewPartition {
  uploaded: MediaAsset[];
  generated: MediaAsset[];
  brand: MediaAsset[];
}

const _BRAND_ORIGINS: ReadonlySet<MediaOrigin> = new Set<MediaOrigin>([
  "STOCK",
  "IMPORTED",
  "EXTERNAL_URL",
]);

/** Partition assets into uploaded / generated / brand views (order preserved). */
export function partitionByView(assets: MediaAsset[]): ViewPartition {
  const uploaded: MediaAsset[] = [];
  const generated: MediaAsset[] = [];
  const brand: MediaAsset[] = [];
  for (const asset of assets) {
    if (asset.origin === "UPLOADED") {
      uploaded.push(asset);
    } else if (asset.origin === "GENERATED") {
      generated.push(asset);
    } else if (_BRAND_ORIGINS.has(asset.origin)) {
      brand.push(asset);
    }
  }
  return { uploaded, generated, brand };
}

function assetsForView(assets: MediaAsset[], view: LibraryView): MediaAsset[] {
  if (view === "all") {
    return assets;
  }
  return partitionByView(assets)[view];
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; assets: MediaAsset[] };

export interface MediaLibraryProps {
  workspaceId: number;
  selectedId?: number | null;
  onSelect?: (assetId: number) => void;
}

export default function MediaLibrary({
  workspaceId,
  selectedId = null,
  onSelect,
}: MediaLibraryProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [view, setView] = useState<LibraryView>("all");
  const requestedWorkspace = useRef<number | null>(null);

  useEffect(() => {
    if (requestedWorkspace.current === workspaceId) {
      return;
    }
    requestedWorkspace.current = workspaceId;
    let cancelled = false;
    setState({ status: "loading" });
    listWorkspaceAssets(workspaceId)
      .then((page) => {
        if (!cancelled) {
          setState({ status: "ready", assets: page.items });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load assets";
          setState({ status: "error", message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [workspaceId]);

  if (state.status === "loading") {
    return (
      <div data-testid="media-library" data-status="loading">
        Loading assets…
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div data-testid="media-library" data-status="error">
        {state.message}
      </div>
    );
  }

  if (state.assets.length === 0) {
    return (
      <div data-testid="media-library" data-status="empty">
        No assets yet — upload or generate media to get started.
      </div>
    );
  }

  const visible = assetsForView(state.assets, view);

  return (
    <div data-testid="media-library" data-status="ready">
      <div role="tablist" style={{ display: "flex", gap: 6, marginBottom: 8 }}>
        {(["all", "uploaded", "generated", "brand"] as LibraryView[]).map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            data-testid={`view-tab-${v}`}
            aria-selected={view === v}
            onClick={() => setView(v)}
          >
            {v}
          </button>
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {visible.map((asset) => {
          const selected = selectedId === asset.id;
          const dimensions =
            asset.width !== null && asset.height !== null
              ? `${asset.width}×${asset.height}`
              : asset.duration_seconds !== null
                ? `${asset.duration_seconds}s`
                : "";
          return (
            <div
              key={asset.id}
              data-testid={`asset-card-${asset.id}`}
              data-asset-id={String(asset.id)}
              data-selected={selected ? "true" : "false"}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              onClick={() => onSelect?.(asset.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect?.(asset.id);
                }
              }}
              style={{
                width: 120,
                border: selected ? "2px solid #e5484d" : "1px solid #555",
                borderRadius: 6,
                overflow: "hidden",
                background: "#1f1f1f",
                cursor: "pointer",
              }}
            >
              {asset.storage_key !== null && asset.media_type === "VIDEO" ? (
                <video
                  data-testid={`asset-preview-${asset.id}`}
                  src={workspaceAssetUrl(asset)}
                  muted
                  preload="metadata"
                  style={{ width: "100%", height: 80, objectFit: "cover", display: "block" }}
                />
              ) : asset.storage_key !== null && asset.media_type !== "AUDIO" ? (
                <img
                  data-testid={`asset-preview-${asset.id}`}
                  src={workspaceAssetUrl(asset)}
                  alt=""
                  style={{ width: "100%", height: 80, objectFit: "cover", display: "block" }}
                />
              ) : (
                <div
                  data-testid={`asset-preview-${asset.id}`}
                  style={{ height: 80, display: "flex", alignItems: "center", justifyContent: "center" }}
                >
                  {asset.media_type === "AUDIO" ? "🔊" : "🖼️"}
                </div>
              )}
              <div style={{ padding: 4, fontSize: 10, color: "#b0b0b0" }}>
                <div>{asset.media_type.toLowerCase()}</div>
                {dimensions && <div>{dimensions}</div>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
