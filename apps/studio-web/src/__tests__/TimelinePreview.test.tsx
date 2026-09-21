import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import TimelinePreview from "../components/creator/TimelinePreview";
import { segmentAtTime } from "../components/creator/TimelinePreview";
import type { RenderPlan } from "../api/timelinePreview";
import { fetchTimelinePreview } from "../api/timelinePreview";

vi.mock("../api/timelinePreview", async () => {
  const actual = await vi.importActual<typeof import("../api/timelinePreview")>(
    "../api/timelinePreview",
  );
  return { ...actual, fetchTimelinePreview: vi.fn() };
});

const mockedFetch = vi.mocked(fetchTimelinePreview);

function fixturePlan(): RenderPlan {
  return {
    segments: [
      {
        kind: "image",
        source: "workspaces/1/assets/a.png",
        timeline_start_seconds: 0,
        duration_seconds: 4,
        trim_start_seconds: null,
        trim_end_seconds: null,
        fit_mode: "cover",
        transition: null,
      },
      {
        kind: "video",
        source: "workspaces/1/assets/b.mp4",
        timeline_start_seconds: 4,
        duration_seconds: 4,
        trim_start_seconds: null,
        trim_end_seconds: null,
        fit_mode: "contain",
        transition: "fade",
      },
    ],
    output_spec: { width: 1080, height: 1920, fps: 30 },
    encoding_profile: {
      name: "preview",
      video_codec: "libx264",
      audio_codec: "aac",
      crf: 28,
      preset: "veryfast",
    },
    narration_path: "workspaces/1/render/narration.mp3",
    subtitle_path: "workspaces/1/render/subs.srt",
    music_path: null,
  };
}

describe("segmentAtTime", () => {
  const plan = fixturePlan();

  it("returns null before the first segment when timeline starts later", () => {
    const shifted: RenderPlan = {
      ...plan,
      segments: [{ ...plan.segments[0], timeline_start_seconds: 2 }, plan.segments[1]],
    };
    expect(segmentAtTime(shifted, 0)).toBeNull();
  });

  it("returns the first segment inside its window", () => {
    expect(segmentAtTime(plan, 0)?.source).toBe("workspaces/1/assets/a.png");
    expect(segmentAtTime(plan, 3.9)?.source).toBe("workspaces/1/assets/a.png");
  });

  it("returns the second segment inside its window", () => {
    expect(segmentAtTime(plan, 4)?.source).toBe("workspaces/1/assets/b.mp4");
    expect(segmentAtTime(plan, 7.9)?.source).toBe("workspaces/1/assets/b.mp4");
  });

  it("treats the boundary as the start of the next segment", () => {
    expect(segmentAtTime(plan, 4)?.kind).toBe("video");
  });

  it("returns null past the end", () => {
    expect(segmentAtTime(plan, 8)).toBeNull();
    expect(segmentAtTime(plan, 99)).toBeNull();
  });
});

describe("TimelinePreview", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("renders loading state before the fetch resolves", () => {
    mockedFetch.mockReturnValue(new Promise(() => {}));
    render(<TimelinePreview projectId={1} />);
    const root = screen.getByTestId("timeline-preview");
    expect(root).toHaveAttribute("data-status", "loading");
  });

  it("renders error state when the fetch rejects", async () => {
    mockedFetch.mockRejectedValue(new Error("Timeline not found"));
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "error");
    });
    expect(screen.getByTestId("timeline-preview")).toHaveTextContent("Timeline not found");
  });

  it("renders ready state and the first segment at t=0", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "ready");
    });
    const img = screen.getByTestId("preview-media");
    expect(img.tagName).toBe("IMG");
    expect(img).toHaveAttribute("src", "workspaces/1/assets/a.png");
  });

  it("reflects the output aspect ratio", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("preview-stage")).toHaveAttribute("data-aspect", "1080x1920");
    });
  });

  it("shows the total duration in the time readout", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("preview-time")).toHaveTextContent("0.0 / 8.0");
    });
  });

  it("switches to the video segment after seeking into its window", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "ready");
    });
    const seek = screen.getByTestId("preview-seek");
    fireEvent.change(seek, { target: { value: "5" } });
    const media = screen.getByTestId("preview-media");
    expect(media.tagName).toBe("VIDEO");
    expect(media).toHaveAttribute("src", "workspaces/1/assets/b.mp4");
  });

  it("toggles play state", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "ready");
    });
    const toggle = screen.getByTestId("preview-play-toggle");
    expect(toggle).toHaveAttribute("data-playing", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("data-playing", "true");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("data-playing", "false");
  });

  it("represents audio and subtitle layers when present", async () => {
    mockedFetch.mockResolvedValue(fixturePlan());
    render(<TimelinePreview projectId={1} />);
    await waitFor(() => {
      expect(screen.getByTestId("timeline-preview")).toHaveAttribute("data-status", "ready");
    });
    expect(screen.getByTestId("preview-audio-layer")).toBeInTheDocument();
    expect(screen.getByTestId("preview-caption-indicator")).toBeInTheDocument();
  });
});
