import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TimelineRuler from "../components/creator/TimelineRuler";
import { computeTicks, chooseTickInterval } from "../components/creator/TimelineRuler";

describe("chooseTickInterval", () => {
  it("uses fine intervals for short drafts", () => {
    expect(chooseTickInterval(15)).toBe(5);
    expect(chooseTickInterval(30)).toBe(5);
  });

  it("scales up for longer short drafts", () => {
    expect(chooseTickInterval(45)).toBe(10);
    expect(chooseTickInterval(60)).toBe(10);
    expect(chooseTickInterval(90)).toBe(15);
  });

  it("never returns a non-positive interval", () => {
    expect(chooseTickInterval(0.5)).toBeGreaterThan(0);
    expect(chooseTickInterval(0)).toBeGreaterThan(0);
  });

  it("handles long custom durations without a duration ceiling", () => {
    expect(chooseTickInterval(600)).toBeGreaterThanOrEqual(60);
    expect(chooseTickInterval(3600)).toBeGreaterThanOrEqual(300);
  });
});

describe("computeTicks", () => {
  it("places a tick at 0 and at each interval up to duration", () => {
    const ticks = computeTicks(30, 300);
    expect(ticks.map((t) => t.seconds)).toEqual([0, 5, 10, 15, 20, 25, 30]);
  });

  it("positions ticks by horizontal fraction of the width", () => {
    const ticks = computeTicks(30, 300);
    // 0s -> 0px, 15s -> 150px, 30s -> 300px
    expect(ticks[0].x).toBeCloseTo(0);
    expect(ticks[3].x).toBeCloseTo(150);
    expect(ticks[ticks.length - 1].x).toBeCloseTo(300);
  });

  it("always includes an end tick at the exact duration", () => {
    const ticks = computeTicks(45, 450);
    const last = ticks[ticks.length - 1];
    expect(last.seconds).toBe(45);
    expect(last.x).toBeCloseTo(450);
  });

  it("labels ticks as M:SS", () => {
    const ticks = computeTicks(90, 900);
    expect(ticks[0].label).toBe("0:00");
    const at60 = ticks.find((t) => t.seconds === 60);
    expect(at60?.label).toBe("1:00");
    const at90 = ticks.find((t) => t.seconds === 90);
    expect(at90?.label).toBe("1:30");
  });

  it("returns a single origin tick for zero/negative duration", () => {
    expect(computeTicks(0, 300).map((t) => t.seconds)).toEqual([0]);
    expect(computeTicks(-5, 300).map((t) => t.seconds)).toEqual([0]);
  });
});

describe("TimelineRuler", () => {
  it("renders a ruler with the accessible total duration", () => {
    render(<TimelineRuler durationSeconds={30} width={300} />);
    const ruler = screen.getByTestId("timeline-ruler");
    expect(ruler).toHaveAttribute("data-duration", "30");
    expect(ruler).toHaveAttribute("role", "img");
    expect(ruler).toHaveAttribute("aria-label", expect.stringContaining("30"));
  });

  it("renders a tick element per computed tick with its label", () => {
    render(<TimelineRuler durationSeconds={30} width={300} />);
    const ticks = screen.getAllByTestId("ruler-tick");
    expect(ticks).toHaveLength(7); // 0,5,10,15,20,25,30
    expect(screen.getByText("0:00")).toBeInTheDocument();
    expect(screen.getByText("0:30")).toBeInTheDocument();
  });

  it.each([15, 30, 45, 60, 90])(
    "renders ticks for a %s-second draft",
    (duration) => {
      render(<TimelineRuler durationSeconds={duration} width={600} />);
      const ruler = screen.getByTestId("timeline-ruler");
      expect(ruler).toHaveAttribute("data-duration", String(duration));
      expect(screen.getAllByTestId("ruler-tick").length).toBeGreaterThan(1);
    },
  );

  it("handles a custom non-standard duration", () => {
    render(<TimelineRuler durationSeconds={37.5} width={375} />);
    const ruler = screen.getByTestId("timeline-ruler");
    expect(ruler).toHaveAttribute("data-duration", "37.5");
    // end tick at the exact custom duration
    expect(screen.getByText("0:37")).toBeInTheDocument();
  });
});
