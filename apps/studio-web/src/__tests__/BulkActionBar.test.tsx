import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import BulkActionBar from "../components/creator/BulkActionBar";
import type { StoryboardParagraph } from "../api/storyboard";

function makeParagraph(overrides: Partial<StoryboardParagraph> = {}): StoryboardParagraph {
  return {
    section_id: "sec-0",
    order: 0,
    text: "Test",
    display_text: null,
    image_prompt: null,
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
    section_type: null,
    speaker: null,
    duration: null,
    turn_kind: null,
    visual_override: null,
    ...overrides,
  };
}

describe("BulkActionBar", () => {
  it("renders nothing when no paragraphs", () => {
    const { container } = render(<BulkActionBar paragraphs={[]} currentStage="SCRIPT_REVIEW" />);
    expect(container.innerHTML).toBe("");
  });

  it("shows remaining counts for all types", () => {
    const paragraphs = [
      makeParagraph({ section_id: "s0", image_url: "/img.png" }),
      makeParagraph({ section_id: "s1" }),
      makeParagraph({ section_id: "s2" }),
    ];
    render(<BulkActionBar paragraphs={paragraphs} currentStage="SUBTITLE_GENERATING" />);
    expect(screen.getByTestId("bulk-gen-images")).toHaveTextContent("Generate All Images (2)");
    expect(screen.getByTestId("bulk-gen-audio")).toHaveTextContent("Generate All Audio (3)");
    expect(screen.getByTestId("bulk-gen-subtitles")).toHaveTextContent("Generate All Subtitles (3)");
  });

  it("shows Done label when all complete", () => {
    const paragraphs = [
      makeParagraph({
        section_id: "s0",
        image_url: "/i.png",
        audio_url: "/a.wav",
        subtitles_url: "/s.srt",
      }),
    ];
    render(<BulkActionBar paragraphs={paragraphs} currentStage="SUBTITLE_GENERATING" />);
    expect(screen.getByTestId("bulk-gen-images")).toHaveTextContent("All Images Done ✓");
    expect(screen.getByTestId("bulk-gen-audio")).toHaveTextContent("All Audio Done ✓");
    expect(screen.getByTestId("bulk-gen-subtitles")).toHaveTextContent("All Subtitles Done ✓");
  });

  it("disables buttons when generating prop is true", () => {
    const paragraphs = [makeParagraph()];
    render(<BulkActionBar paragraphs={paragraphs} currentStage="SUBTITLE_GENERATING" generating />);
    expect(screen.getByTestId("bulk-gen-images")).toBeDisabled();
    expect(screen.getByTestId("bulk-gen-audio")).toBeDisabled();
    expect(screen.getByTestId("bulk-gen-subtitles")).toBeDisabled();
  });

  it("disables buttons when any paragraph is generating", () => {
    const paragraphs = [makeParagraph({ status: "generating_audio" })];
    render(<BulkActionBar paragraphs={paragraphs} currentStage="SUBTITLE_GENERATING" />);
    expect(screen.getByTestId("bulk-gen-images")).toBeDisabled();
  });

  it("calls onGenerateAllImages when clicked", () => {
    const onClick = vi.fn();
    render(
        <BulkActionBar
          paragraphs={[makeParagraph()]}
          currentStage="VISUAL_ASSET_GENERATING"
          onGenerateAllImages={onClick}
        />,
    );
    fireEvent.click(screen.getByTestId("bulk-gen-images"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("calls onGenerateAllAudio when clicked", () => {
    const onClick = vi.fn();
    render(
        <BulkActionBar
          paragraphs={[makeParagraph()]}
          currentStage="AUDIO_GENERATING"
          onGenerateAllAudio={onClick}
        />,
    );
    fireEvent.click(screen.getByTestId("bulk-gen-audio"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("calls onGenerateAllSubtitles when clicked", () => {
    const onClick = vi.fn();
    render(
        <BulkActionBar
          paragraphs={[makeParagraph()]}
          currentStage="SUBTITLE_GENERATING"
          onGenerateAllSubtitles={onClick}
        />,
    );
    fireEvent.click(screen.getByTestId("bulk-gen-subtitles"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("disables done buttons (0 remaining)", () => {
    const onClick = vi.fn();
    const paragraphs = [
      makeParagraph({ image_url: "/i.png", audio_url: "/a.wav", subtitles_url: "/s.srt" }),
    ];
    render(
        <BulkActionBar
          paragraphs={paragraphs}
          currentStage="SUBTITLE_GENERATING"
          onGenerateAllImages={onClick}
        />,
    );
    expect(screen.getByTestId("bulk-gen-images")).toBeDisabled();
  });
});
