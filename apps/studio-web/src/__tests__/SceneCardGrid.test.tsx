import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SceneCardGrid from "../components/creator/SceneCardGrid";
import type { StoryboardParagraph } from "../api/storyboard";

function makeParagraph(overrides: Partial<StoryboardParagraph> = {}): StoryboardParagraph {
  return {
    section_id: "sec-0",
    order: 0,
    text: "Test text",
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
    ...overrides,
  };
}

function makeNParagraphs(n: number): StoryboardParagraph[] {
  return Array.from({ length: n }, (_, i) =>
    makeParagraph({ section_id: `sec-${i}`, order: i, scene_id: `scene-${i}`, text: `Paragraph ${i + 1}` }),
  );
}

describe("SceneCardGrid", () => {
  it("shows empty state when no paragraphs", () => {
    render(<SceneCardGrid paragraphs={[]} />);
    expect(screen.getByTestId("scene-card-grid-empty")).toBeInTheDocument();
    expect(screen.getByTestId("scene-card-grid-empty")).toHaveTextContent("No scenes");
  });

  it("renders 1 scene card", () => {
    render(<SceneCardGrid paragraphs={makeNParagraphs(1)} />);
    expect(screen.getByTestId("scene-card-grid")).toBeInTheDocument();
    expect(screen.getByTestId("scene-card-sec-0")).toBeInTheDocument();
  });

  it("renders 5 scene cards", () => {
    render(<SceneCardGrid paragraphs={makeNParagraphs(5)} />);
    for (let i = 0; i < 5; i++) {
      expect(screen.getByTestId(`scene-card-sec-${i}`)).toBeInTheDocument();
    }
  });

  it("renders 10 scene cards", () => {
    render(<SceneCardGrid paragraphs={makeNParagraphs(10)} />);
    const grid = screen.getByTestId("scene-card-grid");
    expect(grid.children).toHaveLength(10);
  });

  it("passes disabled prop to all cards", () => {
    const onGenImage = vi.fn();
    const paragraphs = [makeParagraph({ scene_id: "scene-0" })];
    render(
      <SceneCardGrid
        paragraphs={paragraphs}
        onGenerateImage={onGenImage}
        disabled
      />,
    );
    // When disabled, action buttons should not be rendered
    expect(screen.queryByTestId("gen-image-sec-0")).not.toBeInTheDocument();
  });

  it("renders grid container with correct test id", () => {
    render(<SceneCardGrid paragraphs={makeNParagraphs(3)} />);
    expect(screen.getByTestId("scene-card-grid")).toBeInTheDocument();
  });
});
