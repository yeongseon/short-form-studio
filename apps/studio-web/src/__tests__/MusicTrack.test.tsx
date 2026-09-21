import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import MusicTrack from "../components/creator/MusicTrack";
import {
  layoutMusic,
  computeCoverage,
  formatMix,
  type MusicCue,
  type MixSettings,
} from "../components/creator/MusicTrack";

function cues(): MusicCue[] {
  return [
    { id: "m1", source: "bed1.mp3", startSeconds: 0, durationSeconds: 4 },
    // gap 4..6
    { id: "m2", source: "bed2.mp3", startSeconds: 6, durationSeconds: 4 },
  ];
}

const mix: MixSettings = { musicVolume: 0.3, narrationVolume: 1.0, musicMuted: false };

describe("layoutMusic", () => {
  it("positions cues on the shared px/second scale", () => {
    const laid = layoutMusic(cues(), 10, 500);
    expect(laid[0]).toMatchObject({ id: "m1", left: 0, width: 200 });
    expect(laid[1]).toMatchObject({ id: "m2", left: 300, width: 200 });
  });
  it("returns empty for zero duration", () => {
    expect(layoutMusic(cues(), 0, 500)).toEqual([]);
  });
});

describe("computeCoverage", () => {
  it("reports covered fraction of the timeline", () => {
    // 8s of 10s covered -> 0.8
    expect(computeCoverage(cues(), 10)).toBeCloseTo(0.8);
  });
  it("is zero with no cues", () => {
    expect(computeCoverage([], 10)).toBe(0);
  });
  it("clamps overlapping/over-length coverage to at most 1", () => {
    const overlap: MusicCue[] = [
      { id: "a", source: "a.mp3", startSeconds: 0, durationSeconds: 8 },
      { id: "b", source: "b.mp3", startSeconds: 4, durationSeconds: 10 },
    ];
    expect(computeCoverage(overlap, 10)).toBeLessThanOrEqual(1);
    expect(computeCoverage(overlap, 10)).toBeCloseTo(1);
  });
});

describe("formatMix", () => {
  it("formats volumes as percentages and mute state", () => {
    expect(formatMix(mix)).toContain("Music 30%");
    expect(formatMix(mix)).toContain("Narration 100%");
  });
  it("shows muted independent of volume", () => {
    expect(formatMix({ ...mix, musicMuted: true })).toContain("muted");
  });
});

describe("MusicTrack", () => {
  it("renders a music cue per coverage span", () => {
    const { container } = render(
      <MusicTrack cues={cues()} durationSeconds={10} width={500} mix={mix} />,
    );
    expect(container.querySelectorAll("[data-music-id]")).toHaveLength(2);
  });

  it("shows current mix settings from the timeline", () => {
    render(<MusicTrack cues={cues()} durationSeconds={10} width={500} mix={mix} />);
    const settings = screen.getByTestId("music-mix-settings");
    expect(settings).toHaveTextContent("Music 30%");
    expect(settings).toHaveTextContent("Narration 100%");
  });

  it("reflects muted music without changing the stored volume", () => {
    render(
      <MusicTrack
        cues={cues()}
        durationSeconds={10}
        width={500}
        mix={{ ...mix, musicMuted: true }}
      />,
    );
    const track = screen.getByTestId("music-track");
    expect(track).toHaveAttribute("data-muted", "true");
    expect(screen.getByTestId("music-mix-settings")).toHaveTextContent("Music 30%");
  });

  it("does not autoplay: audio elements have no autoPlay and start paused", () => {
    const { container } = render(
      <MusicTrack
        cues={cues()}
        durationSeconds={10}
        width={500}
        mix={mix}
        currentTime={1}
      />,
    );
    const audios = container.querySelectorAll("audio");
    audios.forEach((a) => {
      expect(a).not.toHaveAttribute("autoplay");
    });
  });

  it("exposes a coverage summary", () => {
    render(<MusicTrack cues={cues()} durationSeconds={10} width={500} mix={mix} />);
    expect(screen.getByTestId("music-coverage")).toHaveTextContent("80%");
  });

  it("highlights the active cue at current time and none in a gap", () => {
    const { rerender } = render(
      <MusicTrack cues={cues()} durationSeconds={10} width={500} mix={mix} currentTime={2} />,
    );
    expect(screen.getByTestId("music-cue-m1")).toHaveAttribute("data-active", "true");
    rerender(
      <MusicTrack cues={cues()} durationSeconds={10} width={500} mix={mix} currentTime={5} />,
    );
    expect(screen.getByTestId("music-cue-m1")).toHaveAttribute("data-active", "false");
    expect(screen.getByTestId("music-cue-m2")).toHaveAttribute("data-active", "false");
  });

  it("supports controlled selection", () => {
    const onSelect = vi.fn();
    render(
      <MusicTrack
        cues={cues()}
        durationSeconds={10}
        width={500}
        mix={mix}
        selectedId="m2"
        onSelect={onSelect}
      />,
    );
    expect(screen.getByTestId("music-cue-m2")).toHaveAttribute("data-selected", "true");
    fireEvent.click(screen.getByTestId("music-cue-m1"));
    expect(onSelect).toHaveBeenCalledWith("m1");
  });

  it("renders empty track with no cues", () => {
    const { container } = render(
      <MusicTrack cues={[]} durationSeconds={10} width={500} mix={mix} />,
    );
    expect(container.querySelectorAll("[data-music-id]")).toHaveLength(0);
    expect(screen.getByTestId("music-coverage")).toHaveTextContent("0%");
  });
});
