import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import VisualAssetGrid from "../components/creator/VisualAssetGrid";
import type { AssetData } from "../components/creator/VisualAssetGrid";

// --------------- helpers ---------------

const API = "/api/creator";
const RUN_ID = 50;

function makeAsset(
  id: number,
  sceneId: string,
  version: number,
  overrides: Partial<AssetData> = {},
): AssetData {
  return {
    id,
    run_id: RUN_ID,
    scene_id: sceneId,
    version,
    asset_path: `data/artifacts/1/${RUN_ID}/${sceneId}_v${version}.png`,
    prompt_snapshot: `Prompt for ${sceneId} v${version}`,
    model_used: "sd15",
    provider_type: "local-gpu",
    is_active: version === 1,
    created_at: "2026-01-15T10:00:00Z",
    ...overrides,
  };
}

function mockFetch(responses: Record<string, { status?: number; body: unknown }>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    for (const [pattern, resp] of Object.entries(responses)) {
      if (key.includes(pattern) || url.includes(pattern)) {
        return {
          ok: (resp.status ?? 200) < 400,
          status: resp.status ?? 200,
          json: async () => resp.body,
        };
      }
    }
    return { ok: false, status: 404, json: async () => ({ detail: "Not found" }) };
  }) as unknown as typeof fetch;
}

// --------------- tests ---------------

describe("VisualAssetGrid", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("shows loading state initially", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} />);
    expect(screen.getByTestId("asset-grid-loading")).toHaveTextContent("Loading visual assets");
  });

  it("loads and renders scene groups", async () => {
    const response = {
      run_id: RUN_ID,
      scenes: {
        "scene-0": [
          makeAsset(1, "scene-0", 2, { is_active: true }),
          makeAsset(2, "scene-0", 1, { is_active: false }),
        ],
        "scene-1": [makeAsset(3, "scene-1", 1, { is_active: true })],
      },
      total_scenes: 2,
      total_assets: 3,
    };
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: { body: response },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scene-group-scene-0")).toBeInTheDocument();
    expect(screen.getByTestId("scene-group-scene-1")).toBeInTheDocument();
    expect(screen.getByTestId("asset-1")).toBeInTheDocument();
    expect(screen.getByTestId("asset-2")).toBeInTheDocument();
    expect(screen.getByTestId("asset-3")).toBeInTheDocument();
    expect(screen.getByText("2 scenes · 3 assets")).toBeInTheDocument();
  });

  it("shows empty state when no assets", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: {
        body: { run_id: RUN_ID, scenes: {}, total_scenes: 0, total_assets: 0 },
      },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid-empty")).toBeInTheDocument();
    });
    expect(screen.getByText("No visual assets yet")).toBeInTheDocument();
  });

  it("shows error when load fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: {
        status: 404,
        body: { detail: "Run not found" },
      },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid-error")).toHaveTextContent("Run not found");
    });
    expect(onError).toHaveBeenCalledWith("load", "Run not found");
  });

  it("marks active asset visually", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: {
        body: {
          run_id: RUN_ID,
          scenes: {
            "scene-0": [
              makeAsset(10, "scene-0", 2, { is_active: true }),
              makeAsset(11, "scene-0", 1, { is_active: false }),
            ],
          },
          total_scenes: 1,
          total_assets: 2,
        },
      },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    // Active asset has badge
    expect(screen.getByTestId("asset-10-active")).toHaveTextContent("Active");
    // Inactive asset has select button, no badge
    expect(screen.queryByTestId("asset-11-active")).not.toBeInTheDocument();
    expect(screen.getByTestId("asset-11-select")).toHaveTextContent("Set Active");
  });

  it("displays asset metadata", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: {
        body: {
          run_id: RUN_ID,
          scenes: {
            "scene-0": [makeAsset(20, "scene-0", 1, {
              is_active: true,
              prompt_snapshot: "A serene landscape",
              model_used: "sd15",
            })],
          },
          total_scenes: 1,
          total_assets: 1,
        },
      },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("asset-20-prompt")).toHaveTextContent("A serene landscape");
    expect(screen.getByTestId("asset-20-model")).toHaveTextContent("Model: sd15");
    expect(screen.getByTestId("asset-20-time")).toBeInTheDocument();
  });

  it("readOnly mode hides select buttons", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-assets`]: {
        body: {
          run_id: RUN_ID,
          scenes: {
            "scene-0": [
              makeAsset(30, "scene-0", 2, { is_active: true }),
              makeAsset(31, "scene-0", 1, { is_active: false }),
            ],
          },
          total_scenes: 1,
          total_assets: 2,
        },
      },
    });
    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} readOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    // No select button for inactive asset in readOnly mode
    expect(screen.queryByTestId("asset-31-select")).not.toBeInTheDocument();
  });

  it("select button triggers API call and refreshes", async () => {
    const onSelect = vi.fn();
    const initialData = {
      run_id: RUN_ID,
      scenes: {
        "scene-0": [
          makeAsset(40, "scene-0", 2, { is_active: true }),
          makeAsset(41, "scene-0", 1, { is_active: false }),
        ],
      },
      total_scenes: 1,
      total_assets: 2,
    };
    const updatedData = {
      ...initialData,
      scenes: {
        "scene-0": [
          makeAsset(40, "scene-0", 2, { is_active: false }),
          makeAsset(41, "scene-0", 1, { is_active: true }),
        ],
      },
    };
    const selectedAsset = makeAsset(41, "scene-0", 1, { is_active: true });

    let callCount = 0;
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST" && (url as string).includes("/select/41")) {
        return {
          ok: true,
          status: 200,
          json: async () => selectedAsset,
        };
      }
      if ((url as string).includes("/visual-assets") && method === "GET") {
        callCount++;
        return {
          ok: true,
          status: 200,
          json: async () => (callCount <= 1 ? initialData : updatedData),
        };
      }
      return { ok: false, status: 404, json: async () => ({ detail: "Not found" }) };
    }) as unknown as typeof fetch;

    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} onSelect={onSelect} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("asset-41-select"));
    });

    await waitFor(() => {
      expect(onSelect).toHaveBeenCalledWith(selectedAsset);
    });

    // Verify POST was called
    const postCall = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (call: any[]) => (call[1] as RequestInit | undefined)?.method === "POST",
    );
    expect(postCall).toBeDefined();
    expect(postCall![0]).toContain("/select/41");
  });

  it("shows error when select fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "POST") {
        return {
          ok: false,
          status: 400,
          json: async () => ({ detail: "Asset does not belong to scene" }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({
          run_id: RUN_ID,
          scenes: {
            "scene-0": [
              makeAsset(50, "scene-0", 2, { is_active: true }),
              makeAsset(51, "scene-0", 1, { is_active: false }),
            ],
          },
          total_scenes: 1,
          total_assets: 2,
        }),
      };
    }) as unknown as typeof fetch;

    render(<VisualAssetGrid runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("asset-grid")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("asset-51-select"));
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith("select", "Asset does not belong to scene");
    });
  });
});
