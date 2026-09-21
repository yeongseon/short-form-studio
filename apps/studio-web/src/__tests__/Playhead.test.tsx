import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import Playhead from "../components/creator/Playhead";
import {
  clampTime,
  tickPlayback,
  seekTo,
  type PlaybackState,
} from "../components/creator/Playhead";

describe("clampTime", () => {
  it("clamps below zero to zero", () => {
    expect(clampTime(-3, 10)).toBe(0);
  });
  it("clamps above duration to duration", () => {
    expect(clampTime(15, 10)).toBe(10);
  });
  it("passes through in-range values", () => {
    expect(clampTime(4.2, 10)).toBe(4.2);
  });
});

describe("tickPlayback", () => {
  // Drift-free: elapsed is derived from the wall-clock anchor, not accumulated.
  const base: PlaybackState = {
    playing: true,
    anchorWallMs: 1000,
    anchorTime: 2,
    duration: 10,
  };

  it("derives current time from wall-clock delta since the anchor", () => {
    // 3500ms wall time = 2500ms since anchor -> +2.5s -> 4.5s
    expect(tickPlayback(base, 3500).currentTime).toBeCloseTo(4.5);
  });

  it("does not accumulate drift across repeated ticks", () => {
    const t1 = tickPlayback(base, 3000);
    const t2 = tickPlayback(base, 5000);
    // both computed from the same anchor, so exact regardless of call cadence
    expect(t1.currentTime).toBeCloseTo(4.0);
    expect(t2.currentTime).toBeCloseTo(6.0);
  });

  it("stops at the end and marks not playing", () => {
    const res = tickPlayback(base, 20000);
    expect(res.currentTime).toBe(10);
    expect(res.playing).toBe(false);
  });

  it("is a no-op when paused", () => {
    const paused: PlaybackState = { ...base, playing: false };
    expect(tickPlayback(paused, 9999).currentTime).toBe(paused.anchorTime);
  });
});

describe("seekTo", () => {
  const base: PlaybackState = {
    playing: true,
    anchorWallMs: 1000,
    anchorTime: 2,
    duration: 10,
  };

  it("re-anchors so playback continues without a jump-back", () => {
    const res = seekTo(base, 7, 4000);
    expect(res.anchorTime).toBe(7);
    expect(res.anchorWallMs).toBe(4000);
    expect(tickPlayback(res, 4000).currentTime).toBeCloseTo(7);
  });

  it("clamps the seek target to [0, duration]", () => {
    expect(seekTo(base, -1, 4000).anchorTime).toBe(0);
    expect(seekTo(base, 99, 4000).anchorTime).toBe(10);
  });
});

describe("Playhead component", () => {
  it("positions the marker by fraction of width", () => {
    render(<Playhead currentTime={5} durationSeconds={10} width={300} />);
    const marker = screen.getByTestId("playhead-marker");
    // 5/10 * 300 = 150px
    expect(marker).toHaveStyle({ left: "150px" });
  });

  it("exposes accessible slider semantics with current/min/max", () => {
    render(<Playhead currentTime={4} durationSeconds={10} width={300} />);
    const slider = screen.getByTestId("playhead-slider");
    expect(slider).toHaveAttribute("role", "slider");
    expect(slider).toHaveAttribute("aria-valuemin", "0");
    expect(slider).toHaveAttribute("aria-valuemax", "10");
    expect(slider).toHaveAttribute("aria-valuenow", "4");
  });

  it("seeks on pointer input via the range control", () => {
    const onSeek = vi.fn();
    render(
      <Playhead currentTime={0} durationSeconds={10} width={300} onSeek={onSeek} />,
    );
    fireEvent.change(screen.getByTestId("playhead-slider"), {
      target: { value: "6" },
    });
    expect(onSeek).toHaveBeenCalledWith(6);
  });

  it("seeks with ArrowRight/ArrowLeft keyboard steps", () => {
    const onSeek = vi.fn();
    render(
      <Playhead currentTime={5} durationSeconds={10} width={300} onSeek={onSeek} />,
    );
    const slider = screen.getByTestId("playhead-slider");
    fireEvent.keyDown(slider, { key: "ArrowRight" });
    expect(onSeek).toHaveBeenLastCalledWith(6);
    fireEvent.keyDown(slider, { key: "ArrowLeft" });
    expect(onSeek).toHaveBeenLastCalledWith(4);
  });

  it("clamps keyboard seeks at the boundaries", () => {
    const onSeek = vi.fn();
    const { rerender } = render(
      <Playhead currentTime={0} durationSeconds={10} width={300} onSeek={onSeek} />,
    );
    fireEvent.keyDown(screen.getByTestId("playhead-slider"), { key: "ArrowLeft" });
    expect(onSeek).toHaveBeenLastCalledWith(0);
    rerender(
      <Playhead currentTime={10} durationSeconds={10} width={300} onSeek={onSeek} />,
    );
    fireEvent.keyDown(screen.getByTestId("playhead-slider"), { key: "ArrowRight" });
    expect(onSeek).toHaveBeenLastCalledWith(10);
  });

  it("jumps to start/end with Home/End", () => {
    const onSeek = vi.fn();
    render(
      <Playhead currentTime={5} durationSeconds={10} width={300} onSeek={onSeek} />,
    );
    const slider = screen.getByTestId("playhead-slider");
    fireEvent.keyDown(slider, { key: "Home" });
    expect(onSeek).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(slider, { key: "End" });
    expect(onSeek).toHaveBeenLastCalledWith(10);
  });
});
