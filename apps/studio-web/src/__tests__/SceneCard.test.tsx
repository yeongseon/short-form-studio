import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SceneCard from "../components/creator/SceneCard";
import type { StoryboardParagraph } from "../api/storyboard";

// --------------- test helpers ---------------

function makeParagraph(overrides: Partial<StoryboardParagraph> = {}): StoryboardParagraph {
  return {
    section_id: "sec-0",
    order: 0,
    text: "Hello world, this is a test paragraph for the scene card.",
    display_text: null,
    image_prompt: "A beautiful sunset",
    image_url: null,
    audio_url: null,
    audio_duration: null,
    subtitles_url: null,
    subtitle_entries: null,
    status: "idle",
    stale_flags: null,
    scene_id: "scene-0",
    image_asset_id: null,
    audio_artifact_id: null,
    subtitle_artifact_id: null,
    ...overrides,
  };
}

describe("SceneCard", () => {
  // ---- rendering ----

  it("renders scene number and text", () => {
    const p = makeParagraph({ order: 2, text: "Test narration text" });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-card-sec-0")).toBeInTheDocument();
    expect(screen.getByText("Scene 3")).toBeInTheDocument();
    expect(screen.getByTestId("scene-text-sec-0")).toHaveTextContent("Test narration text");
  });

  it("prefers display_text over text", () => {
    const p = makeParagraph({ text: "raw", display_text: "Displayed version" });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-text-sec-0")).toHaveTextContent("Displayed version");
  });

  // ---- status badges ----

  it("shows Idle badge when no assets", () => {
    const p = makeParagraph();
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-badge-sec-0")).toHaveTextContent("Idle");
    expect(screen.getByTestId("scene-card-sec-0")).toHaveAttribute("data-status", "idle");
  });

  it("shows Partial badge when some assets present", () => {
    const p = makeParagraph({ image_url: "/img.png" });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-badge-sec-0")).toHaveTextContent("Partial");
  });

  it("shows Ready badge when all 3 assets present", () => {
    const p = makeParagraph({
      image_url: "/img.png",
      audio_url: "/audio.wav",
      subtitles_url: "/subs.srt",
    });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-badge-sec-0")).toHaveTextContent("Ready");
    expect(screen.getByTestId("scene-card-sec-0")).toHaveAttribute("data-status", "ready");
  });

  it("shows Generating badge during generation", () => {
    const p = makeParagraph({ status: "generating_audio" });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("scene-badge-sec-0")).toHaveTextContent("Generating…");
  });

  // ---- asset slots ----

  it("renders 3 asset slots", () => {
    const p = makeParagraph();
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("asset-slot-image")).toBeInTheDocument();
    expect(screen.getByTestId("asset-slot-audio")).toBeInTheDocument();
    expect(screen.getByTestId("asset-slot-subtitle")).toBeInTheDocument();
  });

  it("sets correct asset status for each slot", () => {
    const p = makeParagraph({
      image_url: "/img.png",
      audio_url: null,
      subtitles_url: null,
    });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("asset-slot-image")).toHaveAttribute("data-status", "ready");
    expect(screen.getByTestId("asset-slot-audio")).toHaveAttribute("data-status", "empty");
    expect(screen.getByTestId("asset-slot-subtitle")).toHaveAttribute("data-status", "empty");
  });

  it("shows loading status for the slot being generated", () => {
    const p = makeParagraph({ status: "generating_audio", image_url: "/img.png" });
    render(<SceneCard paragraph={p} />);
    expect(screen.getByTestId("asset-slot-image")).toHaveAttribute("data-status", "ready");
    expect(screen.getByTestId("asset-slot-audio")).toHaveAttribute("data-status", "loading");
    expect(screen.getByTestId("asset-slot-subtitle")).toHaveAttribute("data-status", "empty");
  });

  // ---- action buttons ----

  it("shows Gen Image button when image missing and scene_id exists", () => {
    const onGenImage = vi.fn();
    const p = makeParagraph({ scene_id: "scene-0" });
    render(<SceneCard paragraph={p} onGenerateImage={onGenImage} />);
    const btn = screen.getByTestId("gen-image-sec-0");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onGenImage).toHaveBeenCalledWith("scene-0");
  });

  it("shows Gen Audio button when image exists but audio missing", () => {
    const onGenAudio = vi.fn();
    const p = makeParagraph({ image_url: "/img.png" });
    render(<SceneCard paragraph={p} onGenerateAudio={onGenAudio} />);
    const btn = screen.getByTestId("gen-audio-sec-0");
    fireEvent.click(btn);
    expect(onGenAudio).toHaveBeenCalledWith("sec-0");
  });

  it("shows Gen Subtitles button when audio exists but subtitles missing", () => {
    const onGenSubs = vi.fn();
    const p = makeParagraph({ image_url: "/img.png", audio_url: "/audio.wav" });
    render(<SceneCard paragraph={p} onGenerateSubtitles={onGenSubs} />);
    const btn = screen.getByTestId("gen-subs-sec-0");
    fireEvent.click(btn);
    expect(onGenSubs).toHaveBeenCalledWith("sec-0");
  });

  it("hides all action buttons when disabled", () => {
    const p = makeParagraph({ scene_id: "scene-0" });
    render(
      <SceneCard
        paragraph={p}
        onGenerateImage={vi.fn()}
        onGenerateAudio={vi.fn()}
        onGenerateSubtitles={vi.fn()}
        disabled
      />,
    );
    expect(screen.queryByTestId("gen-image-sec-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("gen-audio-sec-0")).not.toBeInTheDocument();
    expect(screen.queryByTestId("gen-subs-sec-0")).not.toBeInTheDocument();
  });

  it("hides action buttons during generation", () => {
    const p = makeParagraph({ status: "generating_image", scene_id: "scene-0" });
    render(
      <SceneCard paragraph={p} onGenerateImage={vi.fn()} />,
    );
    expect(screen.queryByTestId("gen-image-sec-0")).not.toBeInTheDocument();
  });

  // ---- text expand/collapse ----

  it("toggles text expansion on click", () => {
    const p = makeParagraph({ text: "A".repeat(200) });
    render(<SceneCard paragraph={p} />);
    const textEl = screen.getByTestId("scene-text-sec-0");
    // Initially clamped (has -webkit-line-clamp style)
    fireEvent.click(textEl);
    // After click, expanded — we just verify it doesn't crash and re-renders
    fireEvent.click(textEl);
  });
});
