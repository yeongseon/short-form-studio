import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import TimelineSceneCard from "../components/creator/TimelineSceneCard";
import {
  summarizeScene,
  type TimelineScene,
} from "../components/creator/TimelineSceneCard";

function scene(): TimelineScene {
  return {
    sceneId: "scene-1",
    script: "A calm sunrise over the hills",
    segments: [
      { id: "s1", kind: "image", assetLabel: "sunrise.png", durationSeconds: 3, transition: "fade" },
      { id: "s2", kind: "video", assetLabel: "clouds.mp4", durationSeconds: 2.5, transition: null },
    ],
  };
}

describe("summarizeScene", () => {
  it("totals duration across segments", () => {
    expect(summarizeScene(scene()).totalDuration).toBeCloseTo(5.5);
  });

  it("counts assets by kind", () => {
    const s = summarizeScene(scene());
    expect(s.imageCount).toBe(1);
    expect(s.videoCount).toBe(1);
  });

  it("lists the distinct transitions used", () => {
    expect(summarizeScene(scene()).transitions).toEqual(["fade"]);
  });

  it("handles an empty scene", () => {
    const s = summarizeScene({ sceneId: "x", script: "", segments: [] });
    expect(s.totalDuration).toBe(0);
    expect(s.imageCount).toBe(0);
    expect(s.videoCount).toBe(0);
    expect(s.transitions).toEqual([]);
  });
});

describe("TimelineSceneCard", () => {
  it("shows script, asset, duration and transition summaries", () => {
    render(<TimelineSceneCard scene={scene()} />);
    const card = screen.getByTestId("timeline-scene-card-scene-1");
    expect(card).toHaveTextContent("A calm sunrise over the hills");
    expect(screen.getByTestId("scene-duration-summary")).toHaveTextContent("5.5s");
    expect(screen.getByTestId("scene-asset-summary")).toHaveTextContent("1 image");
    expect(screen.getByTestId("scene-asset-summary")).toHaveTextContent("1 video");
    expect(screen.getByTestId("scene-transition-summary")).toHaveTextContent("fade");
  });

  it("keeps Scene View primary: editor hidden until Edit is pressed", () => {
    render(<TimelineSceneCard scene={scene()} />);
    expect(screen.queryByTestId("scene-editor")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("scene-edit-button"));
    expect(screen.getByTestId("scene-editor")).toBeInTheDocument();
  });

  it("reflects controlled selection via selected prop", () => {
    const { rerender } = render(<TimelineSceneCard scene={scene()} selected={false} />);
    expect(screen.getByTestId("timeline-scene-card-scene-1")).toHaveAttribute(
      "data-selected",
      "false",
    );
    rerender(<TimelineSceneCard scene={scene()} selected />);
    expect(screen.getByTestId("timeline-scene-card-scene-1")).toHaveAttribute(
      "data-selected",
      "true",
    );
  });

  it("emits onSelect (shared selection) when the card is activated", () => {
    const onSelect = vi.fn();
    render(<TimelineSceneCard scene={scene()} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("timeline-scene-card-scene-1"));
    expect(onSelect).toHaveBeenCalledWith("scene-1");
  });

  it("routes editor commands through onCommand without mutating scene directly", () => {
    const onCommand = vi.fn();
    render(<TimelineSceneCard scene={scene()} onCommand={onCommand} />);
    fireEvent.click(screen.getByTestId("scene-edit-button"));
    fireEvent.click(screen.getByTestId("scene-command-retime"));
    expect(onCommand).toHaveBeenCalledWith({ type: "retime", sceneId: "scene-1" });
  });

  it("disables editing when review is locked (preserves review gates)", () => {
    render(<TimelineSceneCard scene={scene()} reviewLocked />);
    const editButton = screen.getByTestId("scene-edit-button");
    expect(editButton).toBeDisabled();
    fireEvent.click(editButton);
    expect(screen.queryByTestId("scene-editor")).not.toBeInTheDocument();
  });
});
