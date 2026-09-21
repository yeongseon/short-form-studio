import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import CaptionTrack from "../components/creator/CaptionTrack";
import {
  layoutCaptions,
  captionAtTime,
  type CaptionCue,
} from "../components/creator/CaptionTrack";

function cues(): CaptionCue[] {
  return [
    { id: "c1", text: "Hello world", startSeconds: 0, endSeconds: 3 },
    // gap 3..5 (no caption)
    { id: "c2", text: "안녕하세요 여러분 오늘도 좋은 하루 되세요", startSeconds: 5, endSeconds: 8 },
    { id: "c3", text: "The end", startSeconds: 8, endSeconds: 10 },
  ];
}

describe("layoutCaptions", () => {
  it("positions cues by start and widths by their own duration", () => {
    const laid = layoutCaptions(cues(), 10, 500);
    expect(laid[0]).toMatchObject({ id: "c1", left: 0, width: 150 });
    expect(laid[1]).toMatchObject({ id: "c2", left: 250, width: 150 });
    expect(laid[2]).toMatchObject({ id: "c3", left: 400, width: 100 });
  });

  it("keeps playhead alignment via shared px/second scale", () => {
    const laid = layoutCaptions(cues(), 10, 300);
    expect(laid[1].left).toBeCloseTo((5 / 10) * 300);
  });

  it("returns empty for zero duration", () => {
    expect(layoutCaptions(cues(), 0, 500)).toEqual([]);
  });
});

describe("captionAtTime", () => {
  const list = cues();

  it("returns the active cue inside its [start, end) window", () => {
    expect(captionAtTime(list, 0)?.id).toBe("c1");
    expect(captionAtTime(list, 2.9)?.id).toBe("c1");
    expect(captionAtTime(list, 6)?.id).toBe("c2");
  });

  it("returns null in a gap between cues", () => {
    expect(captionAtTime(list, 4)).toBeNull();
  });

  it("treats end as exclusive (boundary belongs to next or gap)", () => {
    expect(captionAtTime(list, 3)).toBeNull();
    expect(captionAtTime(list, 8)?.id).toBe("c3");
  });

  it("returns null past the last cue", () => {
    expect(captionAtTime(list, 10)).toBeNull();
    expect(captionAtTime(list, 99)).toBeNull();
  });
});

describe("CaptionTrack", () => {
  it("renders a caption block per cue with its text", () => {
    const { container } = render(
      <CaptionTrack cues={cues()} durationSeconds={10} width={500} />,
    );
    expect(container.querySelectorAll("[data-cue-id]")).toHaveLength(3);
    expect(screen.getByTestId("caption-cue-c1")).toHaveTextContent("Hello world");
  });

  it("renders long/CJK text without clipping (wraps, not truncates)", () => {
    render(<CaptionTrack cues={cues()} durationSeconds={10} width={500} />);
    const cjk = screen.getByTestId("caption-cue-c2");
    // full text present (not cut) and configured to wrap rather than clip
    expect(cjk).toHaveTextContent("안녕하세요 여러분 오늘도 좋은 하루 되세요");
    expect(cjk).toHaveStyle({ whiteSpace: "normal", overflowWrap: "break-word" });
    expect(cjk).not.toHaveStyle({ textOverflow: "ellipsis" });
  });

  it("marks the controlled selected cue", () => {
    render(
      <CaptionTrack cues={cues()} durationSeconds={10} width={500} selectedId="c2" />,
    );
    expect(screen.getByTestId("caption-cue-c2")).toHaveAttribute("data-selected", "true");
    expect(screen.getByTestId("caption-cue-c1")).toHaveAttribute("data-selected", "false");
  });

  it("emits onSelect on click and keyboard without internal selection state", () => {
    const onSelect = vi.fn();
    render(
      <CaptionTrack
        cues={cues()}
        durationSeconds={10}
        width={500}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("caption-cue-c1"));
    expect(onSelect).toHaveBeenLastCalledWith("c1");
    fireEvent.keyDown(screen.getByTestId("caption-cue-c3"), { key: "Enter" });
    expect(onSelect).toHaveBeenLastCalledWith("c3");
    // no selectedId prop -> nothing marked selected
    expect(screen.getByTestId("caption-cue-c1")).toHaveAttribute("data-selected", "false");
  });

  it("highlights the active cue at the current time (preview sync)", () => {
    render(
      <CaptionTrack cues={cues()} durationSeconds={10} width={500} currentTime={6} />,
    );
    expect(screen.getByTestId("caption-cue-c2")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("caption-cue-c1")).toHaveAttribute("data-active", "false");
  });

  it("shows no active cue during a gap", () => {
    render(
      <CaptionTrack cues={cues()} durationSeconds={10} width={500} currentTime={4} />,
    );
    for (const id of ["c1", "c2", "c3"]) {
      expect(screen.getByTestId(`caption-cue-${id}`)).toHaveAttribute("data-active", "false");
    }
  });

  it("renders empty track with no cues", () => {
    const { container } = render(
      <CaptionTrack cues={[]} durationSeconds={10} width={500} />,
    );
    expect(container.querySelectorAll("[data-cue-id]")).toHaveLength(0);
  });
});
