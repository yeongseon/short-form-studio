import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import VoiceTrack from "../components/creator/VoiceTrack";
import {
  layoutNarration,
  computeGaps,
  narrationAtTime,
  type NarrationSegment,
} from "../components/creator/VoiceTrack";

function segments(): NarrationSegment[] {
  return [
    { id: "n1", source: "n1.mp3", startSeconds: 0, durationSeconds: 3 },
    // silent gap 3..5
    { id: "n2", source: "n2.mp3", startSeconds: 5, durationSeconds: 2 },
    // missing media
    { id: "n3", source: null, startSeconds: 7, durationSeconds: 3 },
  ];
}

describe("layoutNarration", () => {
  it("positions segments by start and widths by duration on the shared scale", () => {
    const laid = layoutNarration(segments(), 10, 500);
    expect(laid[0]).toMatchObject({ id: "n1", left: 0, width: 150 });
    expect(laid[1]).toMatchObject({ id: "n2", left: 250, width: 100 });
    expect(laid[2]).toMatchObject({ id: "n3", left: 350, width: 150 });
  });

  it("returns empty for zero duration", () => {
    expect(layoutNarration(segments(), 0, 500)).toEqual([]);
  });
});

describe("computeGaps", () => {
  it("derives silent gaps between segments without mutating timing", () => {
    const gaps = computeGaps(segments(), 10);
    // gap 3..5 between n1 and n2, and 10..10 none at end (n3 ends at 10)
    expect(gaps).toEqual([{ startSeconds: 3, endSeconds: 5 }]);
  });

  it("includes a leading gap when the first segment starts after 0", () => {
    const shifted: NarrationSegment[] = [
      { id: "n1", source: "a.mp3", startSeconds: 2, durationSeconds: 3 },
    ];
    expect(computeGaps(shifted, 8)).toEqual([
      { startSeconds: 0, endSeconds: 2 },
      { startSeconds: 5, endSeconds: 8 },
    ]);
  });

  it("returns a single full gap for no segments", () => {
    expect(computeGaps([], 10)).toEqual([{ startSeconds: 0, endSeconds: 10 }]);
  });
});

describe("narrationAtTime", () => {
  const list = segments();
  it("returns the active narration in its window", () => {
    expect(narrationAtTime(list, 0)?.id).toBe("n1");
    expect(narrationAtTime(list, 6)?.id).toBe("n2");
  });
  it("returns null in a silent gap", () => {
    expect(narrationAtTime(list, 4)).toBeNull();
  });
  it("treats end as exclusive and past-end as null", () => {
    expect(narrationAtTime(list, 3)).toBeNull();
    expect(narrationAtTime(list, 10)).toBeNull();
  });
});

describe("VoiceTrack", () => {
  it("renders a narration block per segment", () => {
    const { container } = render(
      <VoiceTrack segments={segments()} durationSeconds={10} width={500} />,
    );
    expect(container.querySelectorAll("[data-narration-id]")).toHaveLength(3);
  });

  it("renders silent gap markers derived from timing", () => {
    const { container } = render(
      <VoiceTrack segments={segments()} durationSeconds={10} width={500} />,
    );
    const gaps = container.querySelectorAll("[data-gap]");
    expect(gaps).toHaveLength(1);
    // gap 3..5 -> left 150, width 100 on a 500px/10s scale
    expect(gaps[0]).toHaveStyle({ left: "150px", width: "100px" });
  });

  it("flags segments with missing media", () => {
    render(<VoiceTrack segments={segments()} durationSeconds={10} width={500} />);
    expect(screen.getByTestId("voice-seg-n3")).toHaveAttribute("data-missing", "true");
    expect(screen.getByTestId("voice-seg-n1")).toHaveAttribute("data-missing", "false");
  });

  it("highlights the active narration at the current time (preview sync)", () => {
    render(
      <VoiceTrack segments={segments()} durationSeconds={10} width={500} currentTime={6} />,
    );
    expect(screen.getByTestId("voice-seg-n2")).toHaveAttribute("data-active", "true");
    expect(screen.getByTestId("voice-seg-n1")).toHaveAttribute("data-active", "false");
  });

  it("shows no active segment in a silent gap", () => {
    render(
      <VoiceTrack segments={segments()} durationSeconds={10} width={500} currentTime={4} />,
    );
    for (const id of ["n1", "n2", "n3"]) {
      expect(screen.getByTestId(`voice-seg-${id}`)).toHaveAttribute("data-active", "false");
    }
  });

  it("supports controlled selection via selectedId + onSelect", () => {
    const onSelect = vi.fn();
    render(
      <VoiceTrack
        segments={segments()}
        durationSeconds={10}
        width={500}
        selectedId="n2"
        onSelect={onSelect}
      />,
    );
    expect(screen.getByTestId("voice-seg-n2")).toHaveAttribute("data-selected", "true");
    fireEvent.click(screen.getByTestId("voice-seg-n1"));
    expect(onSelect).toHaveBeenCalledWith("n1");
  });

  it("renders empty track with no segments", () => {
    const { container } = render(
      <VoiceTrack segments={[]} durationSeconds={10} width={500} />,
    );
    expect(container.querySelectorAll("[data-narration-id]")).toHaveLength(0);
  });
});
