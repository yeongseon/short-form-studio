import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import PipelineOverviewBar from "../components/creator/PipelineOverviewBar";
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

describe("PipelineOverviewBar", () => {
  it("renders per-type stats", () => {
    const paragraphs = [
      makeParagraph({ section_id: "s0", image_url: "/i.png", audio_url: "/a.wav" }),
      makeParagraph({ section_id: "s1", image_url: "/i2.png" }),
      makeParagraph({ section_id: "s2" }),
    ];
    render(
      <PipelineOverviewBar
        paragraphs={paragraphs}
        totalParagraphs={3}
        readyParagraphs={0}
        renderReady={false}
      />,
    );
    expect(screen.getByTestId("stat-images")).toHaveTextContent("2/3");
    expect(screen.getByTestId("stat-audio")).toHaveTextContent("1/3");
    expect(screen.getByTestId("stat-subtitles")).toHaveTextContent("0/3");
  });

  it("shows ready count", () => {
    render(
      <PipelineOverviewBar
        paragraphs={[]}
        totalParagraphs={5}
        readyParagraphs={3}
        renderReady={false}
      />,
    );
    expect(screen.getByTestId("pipeline-overview-bar")).toHaveTextContent("3/5 ready");
  });

  it("render button is disabled when not ready", () => {
    render(
      <PipelineOverviewBar
        paragraphs={[]}
        totalParagraphs={5}
        readyParagraphs={2}
        renderReady={false}
      />,
    );
    expect(screen.getByTestId("render-btn")).toBeDisabled();
  });

  it("render button is enabled when render ready", () => {
    const onRender = vi.fn();
    render(
      <PipelineOverviewBar
        paragraphs={[]}
        totalParagraphs={5}
        readyParagraphs={5}
        renderReady={true}
        onRender={onRender}
      />,
    );
    const btn = screen.getByTestId("render-btn");
    expect(btn).not.toBeDisabled();
    fireEvent.click(btn);
    expect(onRender).toHaveBeenCalledTimes(1);
  });

  it("render button shows Rendering when rendering prop is true", () => {
    render(
      <PipelineOverviewBar
        paragraphs={[]}
        totalParagraphs={5}
        readyParagraphs={5}
        renderReady={true}
        rendering
      />,
    );
    expect(screen.getByTestId("render-btn")).toHaveTextContent("Rendering…");
    expect(screen.getByTestId("render-btn")).toBeDisabled();
  });

  it("progress bar exists", () => {
    render(
      <PipelineOverviewBar
        paragraphs={[]}
        totalParagraphs={10}
        readyParagraphs={5}
        renderReady={false}
      />,
    );
    expect(screen.getByTestId("progress-bar")).toBeInTheDocument();
  });
});
