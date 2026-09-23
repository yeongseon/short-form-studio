import { afterEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TimelinePreview from "../components/creator/TimelinePreview";

afterEach(() => { vi.restoreAllMocks(); });

function respond(kind: "image" | "video") {
  vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response(JSON.stringify({
    timeline_revision: 17,
    segments: [{ kind, source: "workspaces/7/assets/sample", media_url: "/api/creator/projects/72/assets/9/content",
      timeline_start_seconds: 0, duration_seconds: 5, fit_mode: "contain" }],
    output_spec: { width: 1080, height: 1920, fps: 30 },
    narration_path: null, music_path: null, subtitle_path: null,
  })));
}

it.each(["image", "video"] as const)("uses the served %s URL and signals its revision only after media loads", async (kind) => {
  respond(kind);
  const onReady = vi.fn();
  render(<TimelinePreview projectId={72} onReady={onReady} />);
  const media = await screen.findByTestId("preview-media");
  expect(media).toHaveAttribute("src", "/api/creator/projects/72/assets/9/content");
  expect(onReady).not.toHaveBeenCalled();
  if (kind === "image") fireEvent.load(media);
  else fireEvent.loadedData(media);
  expect(onReady).toHaveBeenCalledWith(17);
});

it.each(["image", "video"] as const)("shows a recoverable error when the %s cannot load", async (kind) => {
  respond(kind);
  const onReady = vi.fn();
  render(<TimelinePreview projectId={72} onReady={onReady} />);
  fireEvent.error(await screen.findByTestId("preview-media"));
  expect(await screen.findByRole("alert")).toHaveTextContent(/reload/i);
  expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "error");
  expect(onReady).not.toHaveBeenCalled();
});

it("bounds the portrait preview to the viewport while retaining its aspect ratio", async () => {
  respond("image");
  render(<TimelinePreview projectId={72} />);
  const stage = await screen.findByTestId("preview-stage");
  expect(stage).toHaveStyle({ "max-height": "60vh", "max-width": "100%", "aspect-ratio": "1080 / 1920" });
});

it("does not mark a replacement preview ready merely because the old image loaded", async () => {
  respond("image");
  const onReady = vi.fn();
  const { rerender } = render(<TimelinePreview projectId={72} onReady={onReady} />);
  fireEvent.load(await screen.findByTestId("preview-media"));
  onReady.mockClear();
  rerender(<TimelinePreview projectId={73} onReady={onReady} />);
  await waitFor(() => expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "ready"));
  expect(onReady).not.toHaveBeenCalled();
});
