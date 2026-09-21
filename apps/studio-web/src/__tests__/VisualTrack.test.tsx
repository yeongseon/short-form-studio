import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import VisualTrack from "../components/creator/VisualTrack";
import {
  layoutBlocks,
  groupByScene,
  type VisualBlock,
} from "../components/creator/VisualTrack";

function blocks(): VisualBlock[] {
  return [
    {
      id: "seg-1",
      sceneId: "scene-1",
      kind: "image",
      source: "a.png",
      startSeconds: 0,
      durationSeconds: 4,
    },
    {
      id: "seg-2",
      sceneId: "scene-1",
      kind: "video",
      source: "b.mp4",
      startSeconds: 4,
      durationSeconds: 2,
    },
    {
      id: "seg-3",
      sceneId: "scene-2",
      kind: "image",
      source: "c.png",
      startSeconds: 6,
      durationSeconds: 4,
    },
  ];
}

describe("layoutBlocks", () => {
  it("positions each block by its start fraction and widths by duration fraction", () => {
    const laid = layoutBlocks(blocks(), 10, 500);
    // total duration 10, width 500 -> 50px/s
    expect(laid[0]).toMatchObject({ id: "seg-1", left: 0, width: 200 });
    expect(laid[1]).toMatchObject({ id: "seg-2", left: 200, width: 100 });
    expect(laid[2]).toMatchObject({ id: "seg-3", left: 300, width: 200 });
  });

  it("keeps playhead alignment: block left equals start * pxPerSecond", () => {
    const laid = layoutBlocks(blocks(), 10, 300);
    // a playhead at t=6 would be at 180px; seg-3 starts at 180px too
    expect(laid[2].left).toBeCloseTo((6 / 10) * 300);
  });

  it("returns empty for zero duration", () => {
    expect(layoutBlocks(blocks(), 0, 500)).toEqual([]);
  });
});

describe("groupByScene", () => {
  it("groups blocks by sceneId preserving timeline order", () => {
    const groups = groupByScene(blocks());
    expect(groups.map((g) => g.sceneId)).toEqual(["scene-1", "scene-2"]);
    expect(groups[0].blocks.map((b) => b.id)).toEqual(["seg-1", "seg-2"]);
    expect(groups[1].blocks.map((b) => b.id)).toEqual(["seg-3"]);
  });
});

describe("VisualTrack", () => {
  it("renders a block per segment with mixed image/video kinds", () => {
    const { container } = render(
      <VisualTrack blocks={blocks()} durationSeconds={10} width={500} />,
    );
    const els = container.querySelectorAll("[data-block-id]");
    expect(els).toHaveLength(3);
    expect(screen.getByTestId("visual-block-seg-1")).toHaveAttribute("data-kind", "image");
    expect(screen.getByTestId("visual-block-seg-2")).toHaveAttribute("data-kind", "video");
  });

  it("renders scene group labels", () => {
    render(<VisualTrack blocks={blocks()} durationSeconds={10} width={500} />);
    expect(screen.getByTestId("scene-group-scene-1")).toBeInTheDocument();
    expect(screen.getByTestId("scene-group-scene-2")).toBeInTheDocument();
  });

  it("marks the selected block via the controlled selectedId prop", () => {
    render(
      <VisualTrack blocks={blocks()} durationSeconds={10} width={500} selectedId="seg-2" />,
    );
    expect(screen.getByTestId("visual-block-seg-2")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("visual-block-seg-1")).toHaveAttribute("data-selected", "false");
  });

  it("emits onSelect when a block is clicked (no internal selection state)", () => {
    const onSelect = vi.fn();
    render(
      <VisualTrack
        blocks={blocks()}
        durationSeconds={10}
        width={500}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("visual-block-seg-3"));
    expect(onSelect).toHaveBeenCalledWith("seg-3");
    // without a selectedId prop, nothing is marked selected (single source of truth)
    expect(screen.getByTestId("visual-block-seg-3")).toHaveAttribute("data-selected", "false");
  });

  it("supports keyboard selection via Enter/Space", () => {
    const onSelect = vi.fn();
    render(
      <VisualTrack
        blocks={blocks()}
        durationSeconds={10}
        width={500}
        onSelect={onSelect}
      />,
    );
    const block = screen.getByTestId("visual-block-seg-1");
    fireEvent.keyDown(block, { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("seg-1");
    fireEvent.keyDown(block, { key: " " });
    expect(onSelect).toHaveBeenLastCalledWith("seg-1");
  });

  it("positions blocks consistently with the shared time scale", () => {
    render(<VisualTrack blocks={blocks()} durationSeconds={10} width={500} />);
    const seg3 = screen.getByTestId("visual-block-seg-3");
    expect(seg3).toHaveStyle({ left: "300px", width: "200px" });
  });

  it("renders nothing selectable for an empty track", () => {
    const { container } = render(
      <VisualTrack blocks={[]} durationSeconds={10} width={500} />,
    );
    expect(container.querySelectorAll("[data-block-id]")).toHaveLength(0);
  });
});
