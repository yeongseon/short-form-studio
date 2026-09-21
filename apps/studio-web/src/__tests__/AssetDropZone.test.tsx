import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AssetDropZone from "../components/creator/AssetDropZone";
import { uploadKindForFile } from "../api/assets";
import { uploadAsset } from "../api/assets";
import type { MediaAsset } from "../api/assets";

vi.mock("../api/assets", async () => {
  const actual = await vi.importActual<typeof import("../api/assets")>("../api/assets");
  return { ...actual, uploadAsset: vi.fn() };
});

const mockedUpload = vi.mocked(uploadAsset);

function file(name: string, type: string): File {
  return new File([new Uint8Array([1, 2, 3])], name, { type });
}

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

function drop(target: HTMLElement, files: File[]): void {
  fireEvent.drop(target, { dataTransfer: { files } });
}

describe("uploadKindForFile", () => {
  it("classifies image/video/audio by MIME", () => {
    expect(uploadKindForFile(file("a.png", "image/png"))).toBe("image");
    expect(uploadKindForFile(file("b.mp4", "video/mp4"))).toBe("video");
    expect(uploadKindForFile(file("c.mp3", "audio/mpeg"))).toBe("audio");
  });
  it("returns null for unsupported types", () => {
    expect(uploadKindForFile(file("d.txt", "text/plain"))).toBeNull();
    expect(uploadKindForFile(file("e.bin", ""))).toBeNull();
  });
});

describe("AssetDropZone", () => {
  const onUnhandled = (e: PromiseRejectionEvent) => e.preventDefault();
  beforeEach(() => {
    mockedUpload.mockReset();
    window.addEventListener("unhandledrejection", onUnhandled);
  });
  afterEach(() => {
    window.removeEventListener("unhandledrejection", onUnhandled);
  });

  it("renders an idle drop zone with a keyboard file-input alternative", () => {
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" />);
    const zone = screen.getByTestId("asset-drop-zone");
    expect(zone).toHaveAttribute("data-status", "idle");
    // keyboard alternative: a real file input reachable without dragging
    expect(screen.getByTestId("asset-file-input")).toHaveAttribute("type", "file");
  });

  it("rejects an unsupported drop with an error state and no upload", async () => {
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" />);
    drop(screen.getByTestId("asset-drop-zone"), [file("notes.txt", "text/plain")]);
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "error"),
    );
    expect(screen.getByTestId("asset-drop-zone")).toHaveTextContent(/unsupported/i);
    expect(mockedUpload).not.toHaveBeenCalled();
  });

  it("shows an uploading state then emits a place command via onCommand", async () => {
    const onCommand = vi.fn();
    mockedUpload.mockResolvedValue(asset(42));
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" onCommand={onCommand} />);

    drop(screen.getByTestId("asset-drop-zone"), [file("pic.png", "image/png")]);
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "ready"),
    );
    expect(mockedUpload).toHaveBeenCalledWith(1, "image", expect.any(File));
    // placement is routed through an EditorCommand, not a direct timeline mutation
    expect(onCommand).toHaveBeenCalledWith({
      type: "placeAsset",
      sceneId: "scene-1",
      assetId: 42,
    });
  });

  it("emits a replace command when a targetSegmentId is provided", async () => {
    const onCommand = vi.fn();
    mockedUpload.mockResolvedValue(asset(43));
    render(
      <AssetDropZone
        workspaceId={1}
        sceneId="scene-1"
        targetSegmentId="seg-9"
        onCommand={onCommand}
      />,
    );
    drop(screen.getByTestId("asset-drop-zone"), [file("clip.mp4", "video/mp4")]);
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "ready"),
    );
    expect(onCommand).toHaveBeenCalledWith({
      type: "replaceAsset",
      sceneId: "scene-1",
      segmentId: "seg-9",
      assetId: 43,
    });
  });

  it("shows an error state and emits no command when upload fails", async () => {
    const onCommand = vi.fn();
    mockedUpload.mockRejectedValue(new Error("Upload exceeds maximum allowed size"));
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" onCommand={onCommand} />);
    drop(screen.getByTestId("asset-drop-zone"), [file("big.png", "image/png")]);
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "error"),
    );
    expect(screen.getByTestId("asset-drop-zone")).toHaveTextContent(
      "Upload exceeds maximum allowed size",
    );
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("cancels an in-flight upload without emitting a command", async () => {
    const onCommand = vi.fn();
    let resolveUpload: (value: MediaAsset) => void = () => {};
    mockedUpload.mockReturnValue(
      new Promise((r) => {
        resolveUpload = r;
      }),
    );
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" onCommand={onCommand} />);
    drop(screen.getByTestId("asset-drop-zone"), [file("pic.png", "image/png")]);
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "uploading"),
    );
    fireEvent.click(screen.getByTestId("asset-cancel-upload"));
    resolveUpload(asset(44));
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "idle"),
    );
    expect(onCommand).not.toHaveBeenCalled();
  });

  it("accepts a file chosen via the keyboard file input", async () => {
    const onCommand = vi.fn();
    mockedUpload.mockResolvedValue(asset(45));
    render(<AssetDropZone workspaceId={1} sceneId="scene-1" onCommand={onCommand} />);
    fireEvent.change(screen.getByTestId("asset-file-input"), {
      target: { files: [file("pic.png", "image/png")] },
    });
    await waitFor(() =>
      expect(screen.getByTestId("asset-drop-zone")).toHaveAttribute("data-status", "ready"),
    );
    expect(onCommand).toHaveBeenCalledWith({
      type: "placeAsset",
      sceneId: "scene-1",
      assetId: 45,
    });
  });
});
