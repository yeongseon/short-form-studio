/**
 * VisualAssetGrid — displays scene-grouped visual assets with version selection.
 *
 * Props:
 * - runId: Pipeline run ID
 * - apiBase: API base URL (default: "/api/creator")
 * - readOnly: If true, hide selection controls
 * - onSelect: Callback when user selects a new active asset
 * - onError: Callback for error messages
 */

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../api/client";

const DEFAULT_API = "/api/creator";

// --------------- types ---------------

export interface AssetData {
  id: number;
  run_id: number;
  scene_id: string;
  version: number;
  asset_path: string;
  prompt_snapshot: string | null;
  model_used: string | null;
  provider_type: string | null;
  is_active: boolean;
  created_at: string;
}

interface AssetsResponse {
  run_id: number;
  scenes: Record<string, AssetData[]>;
  total_scenes: number;
  total_assets: number;
}

interface VisualAssetGridProps {
  runId: number;
  apiBase?: string;
  readOnly?: boolean;
  onSelect?: (asset: AssetData) => void;
  onError?: (action: string, message: string) => void;
}

// --------------- component ---------------

export default function VisualAssetGrid({
  runId,
  apiBase = DEFAULT_API,
  readOnly = false,
  onSelect,
  onError,
}: VisualAssetGridProps) {
  const [data, setData] = useState<AssetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<number | null>(null); // asset id being selected

  // ---- fetch assets ----

  const fetchAssets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase}/runs/${runId}/visual-assets`);
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        const msg = body?.detail ?? `Failed to load assets (${res.status})`;
        setError(msg);
        onError?.("load", msg);
        return;
      }
      const json: AssetsResponse = await res.json();
      setData(json);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load assets";
      setError(msg);
      onError?.("load", msg);
    } finally {
      setLoading(false);
    }
  }, [runId, apiBase, onError]);

  useEffect(() => {
    fetchAssets();
  }, [fetchAssets]);

  // ---- select active ----

  const handleSelect = useCallback(
    async (sceneId: string, assetId: number) => {
      setSelecting(assetId);
      try {
        const res = await apiFetch(`${apiBase}/runs/${runId}/visual-assets/${sceneId}/select/${assetId}`,
        { method: "POST" },);
        if (!res.ok) {
          const body = await res.json().catch(() => null);
          const msg = body?.detail ?? `Select failed (${res.status})`;
          onError?.("select", msg);
          return;
        }
        const updated: AssetData = await res.json();
        onSelect?.(updated);
        // Re-fetch to update active states
        await fetchAssets();
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Select failed";
        onError?.("select", msg);
      } finally {
        setSelecting(null);
      }
    },
    [runId, apiBase, onSelect, onError, fetchAssets],
  );

  // ---- render: loading ----

  if (loading) {
    return (
      <div data-testid="asset-grid-loading" style={{ padding: 24, textAlign: "center", color: "#6b7280" }}>
        Loading visual assets…
      </div>
    );
  }

  // ---- render: error ----

  if (error) {
    return (
      <div
        data-testid="asset-grid-error"
        style={{
          padding: "12px 16px",
          background: "#fef2f2",
          border: "1px solid #fca5a5",
          borderRadius: 6,
          color: "#b91c1c",
          fontSize: 13,
        }}
      >
        {error}
      </div>
    );
  }

  // ---- render: empty ----

  if (!data || data.total_assets === 0) {
    return (
      <div
        data-testid="asset-grid-empty"
        style={{
          textAlign: "center",
          padding: 32,
          background: "#f9fafb",
          borderRadius: 8,
          border: "1px dashed #d1d5db",
          color: "#6b7280",
        }}
      >
        <p style={{ margin: "0 0 4px", fontWeight: 600 }}>No visual assets yet</p>
        <p style={{ margin: 0, fontSize: 13 }}>
          Generate images to see them here.
        </p>
      </div>
    );
  }

  // ---- render: grid ----

  const sceneIds = Object.keys(data.scenes).sort();

  return (
    <div data-testid="asset-grid" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <div style={{ fontSize: 13, color: "#6b7280" }}>
        {data.total_scenes} scene{data.total_scenes !== 1 ? "s" : ""} · {data.total_assets} asset{data.total_assets !== 1 ? "s" : ""}
      </div>

      {sceneIds.map((sceneId) => {
        const assets = data.scenes[sceneId];
        return (
          <div
            key={sceneId}
            data-testid={`scene-group-${sceneId}`}
            style={{
              border: "1px solid #e5e7eb",
              borderRadius: 8,
              padding: 16,
              background: "#fff",
            }}
          >
            <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 600 }}>
              {sceneId}
            </h3>

            <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
              {assets.map((asset) => (
                <div
                  key={asset.id}
                  data-testid={`asset-${asset.id}`}
                  style={{
                    width: 180,
                    border: asset.is_active
                      ? "2px solid #4285f4"
                      : "1px solid #d1d5db",
                    borderRadius: 8,
                    padding: 8,
                    background: asset.is_active ? "#eff6ff" : "#f9fafb",
                    position: "relative",
                  }}
                >
                  {/* Active badge */}
                  {asset.is_active && (
                    <span
                      data-testid={`asset-${asset.id}-active`}
                      style={{
                        position: "absolute",
                        top: 4,
                        right: 4,
                        background: "#4285f4",
                        color: "#fff",
                        padding: "1px 6px",
                        borderRadius: 4,
                        fontSize: 10,
                        fontWeight: 600,
                      }}
                    >
                      Active
                    </span>
                  )}

                  {/* Thumbnail placeholder */}
                  <div
                    data-testid={`asset-${asset.id}-thumb`}
                    style={{
                      width: "100%",
                      height: 100,
                      background: "#e5e7eb",
                      borderRadius: 4,
                      marginBottom: 8,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 11,
                      color: "#9ca3af",
                    }}
                  >
                    v{asset.version}
                  </div>

                  {/* Meta info */}
                  <div style={{ fontSize: 11, color: "#6b7280", lineHeight: 1.5 }}>
                    {asset.prompt_snapshot && (
                      <div
                        data-testid={`asset-${asset.id}-prompt`}
                        style={{
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          marginBottom: 2,
                        }}
                        title={asset.prompt_snapshot}
                      >
                        {asset.prompt_snapshot}
                      </div>
                    )}
                    {asset.model_used && (
                      <div data-testid={`asset-${asset.id}-model`}>
                        Model: {asset.model_used}
                      </div>
                    )}
                    <div data-testid={`asset-${asset.id}-time`}>
                      {new Date(asset.created_at).toLocaleString()}
                    </div>
                  </div>

                  {/* Select button */}
                  {!readOnly && !asset.is_active && (
                    <button
                      data-testid={`asset-${asset.id}-select`}
                      disabled={selecting === asset.id}
                      onClick={() => handleSelect(sceneId, asset.id)}
                      style={{
                        width: "100%",
                        marginTop: 8,
                        padding: "4px 8px",
                        border: "1px solid #d1d5db",
                        borderRadius: 4,
                        background: "#fff",
                        cursor: selecting === asset.id ? "wait" : "pointer",
                        fontSize: 11,
                        color: "#374151",
                      }}
                    >
                      {selecting === asset.id ? "Selecting…" : "Set Active"}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
