import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import MediaLibrary from "../components/creator/MediaLibrary";
import { partitionByView, type MediaAsset } from "../components/creator/MediaLibrary";
import { listWorkspaceAssets } from "../api/assets";

vi.mock("../api/assets", async () => {
  const actual = await vi.importActual<typeof import("../api/assets")>("../api/assets");
  return { ...actual, listWorkspaceAssets: vi.fn() };
});

const mockedList = vi.mocked(listWorkspaceAssets);

function asset(id: number, over: Partial<MediaAsset> = {}): MediaAsset {
  return {
    id,
    workspace_id: 1,
    project_id: null,
    run_id: null,
    media_type: "IMAGE",
    origin: "UPLOADED",
    storage_key: `workspaces/1/assets/${id}.png`,
    mime_type: "image/png",
    width: 1080,
    height: 1920,
    duration_seconds: null,
    source_url: null,
    metadata: {},
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function page(items: MediaAsset[]) {
  return { items, total: items.length, limit: 50, offset: 0 };
}

describe("partitionByView", () => {
  const assets = [
    asset(1, { origin: "UPLOADED" }),
    asset(2, { origin: "GENERATED" }),
    asset(3, { origin: "STOCK" }),
    asset(4, { origin: "IMPORTED" }),
  ];

  it("groups uploaded, generated and brand (stock/imported/external) views", () => {
    const views = partitionByView(assets);
    expect(views.uploaded.map((a) => a.id)).toEqual([1]);
    expect(views.generated.map((a) => a.id)).toEqual([2]);
    expect(views.brand.map((a) => a.id).sort()).toEqual([3, 4]);
  });
});

describe("MediaLibrary", () => {
  const onUnhandled = (e: PromiseRejectionEvent) => e.preventDefault();
  beforeEach(() => {
    mockedList.mockReset();
    window.addEventListener("unhandledrejection", onUnhandled);
  });
  afterEach(() => {
    window.removeEventListener("unhandledrejection", onUnhandled);
  });

  it("shows a loading state before assets resolve", () => {
    let resolve: (value: ReturnType<typeof page>) => void = () => {};
    mockedList.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    const { unmount } = render(<MediaLibrary workspaceId={1} />);
    expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "loading");
    unmount();
    resolve(page([]));
  });

  it("shows an error state when the fetch rejects", async () => {
    mockedList.mockRejectedValue(new Error("Not found"));
    render(<MediaLibrary workspaceId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "error"),
    );
    expect(screen.getByTestId("media-library")).toHaveTextContent("Not found");
  });

  it("shows an empty state when there are no assets", async () => {
    mockedList.mockResolvedValue(page([]));
    render(<MediaLibrary workspaceId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "empty"),
    );
  });

  it("renders assets with metadata and previews, uploaded-first", async () => {
    mockedList.mockResolvedValue(
      page([
        asset(2, { origin: "GENERATED" }),
        asset(1, { origin: "UPLOADED" }),
      ]),
    );
    render(<MediaLibrary workspaceId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "ready"),
    );
    // uploaded-first: preserve backend order (uploaded before generated)
    const cards = screen.getAllByTestId(/^asset-card-/);
    expect(cards[0]).toHaveAttribute("data-asset-id", "2");
    // metadata + preview present
    expect(screen.getByTestId("asset-card-1")).toHaveTextContent("1080×1920");
    const preview = screen.getByTestId("asset-preview-1");
    expect(preview.tagName).toBe("IMG");
    expect(preview).toHaveAttribute("src", "/artifacts/workspaces/1/assets/1.png");
  });

  it("filters to the uploaded view", async () => {
    mockedList.mockResolvedValue(
      page([asset(1, { origin: "UPLOADED" }), asset(2, { origin: "GENERATED" })]),
    );
    render(<MediaLibrary workspaceId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "ready"),
    );
    fireEvent.click(screen.getByTestId("view-tab-uploaded"));
    expect(screen.getByTestId("asset-card-1")).toBeInTheDocument();
    expect(screen.queryByTestId("asset-card-2")).not.toBeInTheDocument();
  });

  it("emits onSelect with the chosen asset and marks selection", async () => {
    const onSelect = vi.fn();
    mockedList.mockResolvedValue(page([asset(1)]));
    render(<MediaLibrary workspaceId={1} selectedId={1} onSelect={onSelect} />);
    await waitFor(() =>
      expect(screen.getByTestId("media-library")).toHaveAttribute("data-status", "ready"),
    );
    expect(screen.getByTestId("asset-card-1")).toHaveAttribute("data-selected", "true");
    fireEvent.click(screen.getByTestId("asset-card-1"));
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("requests only the caller's workspace (no cross-workspace id)", async () => {
    mockedList.mockResolvedValue(page([asset(1)]));
    render(<MediaLibrary workspaceId={7} />);
    await waitFor(() => expect(mockedList).toHaveBeenCalled());
    expect(mockedList.mock.calls[0][0]).toBe(7);
  });
});
