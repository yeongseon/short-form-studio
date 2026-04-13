import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useMediaActions } from "../components/creator/useMediaActions";
import type { StoryboardResponse } from "../api/storyboard";

// --------------- helpers ---------------

const RUN_ID = 42;
const MOCK_STORYBOARD: StoryboardResponse = {
  run_id: RUN_ID,
  paragraphs: [
    {
      section_id: "sec-1",
      order: 0,
      text: "Test paragraph",
      display_text: null,
      image_prompt: null,
      image_url: null,
      audio_url: null,
      audio_duration: null,
      subtitles_url: null,
      subtitle_entries: null,
      status: "idle",
      stale_flags: null,
      scene_id: "scene-1",
      image_asset_id: null,
      audio_artifact_id: null,
      subtitle_artifact_id: null,
      section_type: "narration",
      speaker: null,
      duration: null,
      turn_kind: null,
      visual_override: null,
    },
  ],
  render_ready: false,
  total_paragraphs: 1,
  ready_paragraphs: 0,
};

function mockFetch(responses: Record<string, { status?: number; body: unknown }>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const fullUrl = `${method} ${url}`;
    // Try exact match first, then substring match
    let found = responses[fullUrl];
    if (!found) {
      for (const [pattern, resp] of Object.entries(responses)) {
        if (fullUrl.includes(pattern)) {
          found = resp;
          break;
        }
      }
    }
    if (found) {
      return {
        ok: (found.status ?? 200) < 400,
        status: found.status ?? 200,
        json: async () => found.body,
      };
    }
    return { ok: false, status: 404, json: async () => ({ detail: "Not found" }) };
  }) as unknown as typeof fetch;
}

// --------------- tests ---------------

describe("useMediaActions", () => {
  let setStoryboard: ReturnType<typeof vi.fn>;
  let onStatusMessage: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    setStoryboard = vi.fn();
    onStatusMessage = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls onStatusMessage with error when image generation POST fails with 500", async () => {
    globalThis.fetch = mockFetch({
      "POST /api/creator/runs/42/visual-plan/scenes/scene-1/generate-image": {
        status: 500,
        body: { detail: "Server error" },
      },
    });

    const { result } = renderHook(() =>
      useMediaActions({
        runId: RUN_ID,
        imageModel: "sd15",
        storyboard: MOCK_STORYBOARD,
        setStoryboard,
        onStatusMessage,
      }),
    );

    await act(async () => {
      await result.current.onGenerateImage("scene-1");
    });

    // Should show error message, not success
    expect(onStatusMessage).toHaveBeenCalledWith("Server error");
    // Should NOT update storyboard status to generating_image
    expect(setStoryboard).not.toHaveBeenCalled();
  });

  it("calls onStatusMessage with error when image generation POST fails with 400", async () => {
    globalThis.fetch = mockFetch({
      "POST /api/creator/runs/42/visual-plan/scenes/scene-1/generate-image": {
        status: 400,
        body: { detail: "Bad request" },
      },
    });

    const { result } = renderHook(() =>
      useMediaActions({
        runId: RUN_ID,
        imageModel: "sd15",
        storyboard: MOCK_STORYBOARD,
        setStoryboard,
        onStatusMessage,
      }),
    );

    await act(async () => {
      await result.current.onGenerateImage("scene-1");
    });

    expect(onStatusMessage).toHaveBeenCalledWith("Bad request");
    expect(setStoryboard).not.toHaveBeenCalled();
  });

  it("calls onStatusMessage with error when image generation POST fails without detail", async () => {
    globalThis.fetch = mockFetch({
      "POST /api/creator/runs/42/visual-plan/scenes/scene-1/generate-image": {
        status: 503,
        body: {},
      },
    });

    const { result } = renderHook(() =>
      useMediaActions({
        runId: RUN_ID,
        imageModel: "sd15",
        storyboard: MOCK_STORYBOARD,
        setStoryboard,
        onStatusMessage,
      }),
    );

    await act(async () => {
      await result.current.onGenerateImage("scene-1");
    });

    expect(onStatusMessage).toHaveBeenCalledWith("Image generation failed (503)");
    expect(setStoryboard).not.toHaveBeenCalled();
  });

  it("updates storyboard status when image generation POST succeeds", async () => {
    globalThis.fetch = mockFetch({
      "POST /api/creator/runs/42/visual-plan/scenes/scene-1/generate-image": {
        status: 200,
        body: { task_id: "task-123" },
      },
    });

    const { result } = renderHook(() =>
      useMediaActions({
        runId: RUN_ID,
        imageModel: "sd15",
        storyboard: MOCK_STORYBOARD,
        setStoryboard,
        onStatusMessage,
      }),
    );

    await act(async () => {
      await result.current.onGenerateImage("scene-1");
    });

    // Should show success message
    expect(onStatusMessage).toHaveBeenCalledWith("Image generation started for scene scene-1");
    // Should update storyboard
    expect(setStoryboard).toHaveBeenCalled();
  });
});
