import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import StoryboardWorkspace from "../components/creator/StoryboardWorkspace";
import type { StoryboardResponse } from "../api/storyboard";

// Mock the storyboard API
vi.mock("../api/storyboard", () => ({
  fetchStoryboard: vi.fn(),
  generateParagraphAudio: vi.fn(),
  generateParagraphSubtitles: vi.fn(),
  generateAllParagraphAudio: vi.fn().mockResolvedValue({ dispatched: 3 }),
  generateAllParagraphSubtitles: vi.fn().mockResolvedValue({ dispatched: 3 }),
}));

import { fetchStoryboard } from "../api/storyboard";
const mockFetchStoryboard = fetchStoryboard as ReturnType<typeof vi.fn>;

const MOCK_STORYBOARD: StoryboardResponse = {
  run_id: 1,
  paragraphs: [
    {
      section_id: "sec-0",
      order: 0,
      text: "First scene text",
      display_text: null,
      image_prompt: "A sunrise",
      image_url: "/img/0.png",
      audio_url: "/audio/0.wav",
      audio_duration: 5.2,
      subtitles_url: null,
      subtitle_entries: null,
      status: "idle",
      stale_flags: null,
      scene_id: "scene-0",
      image_asset_id: 1,
      audio_artifact_id: 2,
      subtitle_artifact_id: null,
    },
    {
      section_id: "sec-1",
      order: 1,
      text: "Second scene text",
      display_text: null,
      image_prompt: "A sunset",
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
    },
  ],
  render_ready: false,
  total_paragraphs: 2,
  ready_paragraphs: 0,
};

describe("StoryboardWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading skeleton initially", () => {
    mockFetchStoryboard.mockReturnValue(new Promise(() => {})); // never resolves
    render(<StoryboardWorkspace runId={1} />);
    expect(screen.getByTestId("storyboard-workspace-loading")).toBeInTheDocument();
  });

  it("renders storyboard after loading", async () => {
    mockFetchStoryboard.mockResolvedValue(MOCK_STORYBOARD);
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-workspace")).toBeInTheDocument();
    });
    expect(screen.getByTestId("pipeline-overview-bar")).toBeInTheDocument();
    expect(screen.getByTestId("bulk-action-bar")).toBeInTheDocument();
    expect(screen.getByTestId("scene-card-grid")).toBeInTheDocument();
  });

  it("shows error state on fetch failure", async () => {
    mockFetchStoryboard.mockRejectedValue(new Error("Network error"));
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-workspace-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("storyboard-workspace-error")).toHaveTextContent("Network error");
  });

  it("renders correct number of scene cards", async () => {
    mockFetchStoryboard.mockResolvedValue(MOCK_STORYBOARD);
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("scene-card-sec-0")).toBeInTheDocument();
      expect(screen.getByTestId("scene-card-sec-1")).toBeInTheDocument();
    });
  });

  it("shows per-type stats in overview bar", async () => {
    mockFetchStoryboard.mockResolvedValue(MOCK_STORYBOARD);
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("stat-images")).toHaveTextContent("1/2");
      expect(screen.getByTestId("stat-audio")).toHaveTextContent("1/2");
      expect(screen.getByTestId("stat-subtitles")).toHaveTextContent("0/2");
    });
  });

  it("render button is disabled when not ready", async () => {
    mockFetchStoryboard.mockResolvedValue(MOCK_STORYBOARD);
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("render-btn")).toBeDisabled();
    });
  });

  it("render button enabled when all ready", async () => {
    const allReady = {
      ...MOCK_STORYBOARD,
      render_ready: true,
      ready_paragraphs: 2,
      paragraphs: MOCK_STORYBOARD.paragraphs.map((p) => ({
        ...p,
        image_url: "/img.png",
        audio_url: "/audio.wav",
        subtitles_url: "/subs.srt",
        status: "ready" as const,
      })),
    };
    mockFetchStoryboard.mockResolvedValue(allReady);
    render(<StoryboardWorkspace runId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("render-btn")).not.toBeDisabled();
    });
  });
});
