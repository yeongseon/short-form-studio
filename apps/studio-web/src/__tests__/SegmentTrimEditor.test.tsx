import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import SegmentTrimEditor from "../components/creator/SegmentTrimEditor";
import {
  applyTrim,
  createTrimHistory,
  undo,
  redo,
  type TrimState,
  type TrimHistory,
} from "../components/creator/SegmentTrimEditor";

function state(over: Partial<TrimState> = {}): TrimState {
  return {
    sourceDurationSeconds: 10,
    trimStartSeconds: 0,
    trimEndSeconds: 10,
    ...over,
  };
}

describe("applyTrim", () => {
  it("trims the start edge within bounds", () => {
    const next = applyTrim(state(), { edge: "start", seconds: 2 });
    expect(next.trimStartSeconds).toBe(2);
    expect(next.trimEndSeconds).toBe(10);
  });

  it("trims the end edge within bounds", () => {
    const next = applyTrim(state(), { edge: "end", seconds: 7 });
    expect(next.trimEndSeconds).toBe(7);
  });

  it("keeps the effective (timeline) duration equal to end - start", () => {
    const next = applyTrim(state(), { edge: "start", seconds: 3 });
    expect(next.trimEndSeconds - next.trimStartSeconds).toBe(7);
  });

  it("rejects trimming the start past the first frame (below 0)", () => {
    expect(() => applyTrim(state(), { edge: "start", seconds: -1 })).toThrow();
  });

  it("rejects trimming the end past the last frame (beyond source duration)", () => {
    expect(() => applyTrim(state(), { edge: "end", seconds: 11 })).toThrow();
  });

  it("rejects a start >= end (invalid, non-positive duration)", () => {
    expect(() =>
      applyTrim(state({ trimEndSeconds: 5 }), { edge: "start", seconds: 5 }),
    ).toThrow();
    expect(() =>
      applyTrim(state({ trimStartSeconds: 5, trimEndSeconds: 10 }), { edge: "end", seconds: 5 }),
    ).toThrow();
  });

  it("allows trimming exactly to the first/last frame bounds", () => {
    expect(applyTrim(state(), { edge: "start", seconds: 0 }).trimStartSeconds).toBe(0);
    expect(applyTrim(state(), { edge: "end", seconds: 10 }).trimEndSeconds).toBe(10);
  });
});

describe("trim history (undo/redo)", () => {
  function history(): TrimHistory {
    return createTrimHistory(state());
  }

  it("starts with the initial state and cannot undo/redo", () => {
    const h = history();
    expect(h.present.trimStartSeconds).toBe(0);
    expect(h.canUndo).toBe(false);
    expect(h.canRedo).toBe(false);
  });

  it("applies a trim command and enables undo", () => {
    let h = history();
    h = applyTrim(h, { edge: "start", seconds: 2 });
    expect(h.present.trimStartSeconds).toBe(2);
    expect(h.canUndo).toBe(true);
    expect(h.canRedo).toBe(false);
  });

  it("undoes back to the previous state", () => {
    let h = history();
    h = applyTrim(h, { edge: "start", seconds: 2 });
    h = undo(h);
    expect(h.present.trimStartSeconds).toBe(0);
    expect(h.canRedo).toBe(true);
  });

  it("redoes an undone trim", () => {
    let h = history();
    h = applyTrim(h, { edge: "start", seconds: 2 });
    h = undo(h);
    h = redo(h);
    expect(h.present.trimStartSeconds).toBe(2);
    expect(h.canRedo).toBe(false);
  });

  it("clears the redo stack when a new trim is applied after undo", () => {
    let h = history();
    h = applyTrim(h, { edge: "start", seconds: 2 });
    h = undo(h);
    h = applyTrim(h, { edge: "end", seconds: 8 });
    expect(h.canRedo).toBe(false);
    expect(h.present.trimEndSeconds).toBe(8);
  });

  it("undo/redo are no-ops at the boundaries", () => {
    let h = history();
    expect(undo(h).present.trimStartSeconds).toBe(0);
    h = applyTrim(h, { edge: "start", seconds: 2 });
    expect(redo(h).present.trimStartSeconds).toBe(2);
  });
});

describe("SegmentTrimEditor", () => {
  it("shows current trim and effective duration", () => {
    render(
      <SegmentTrimEditor
        segmentId="seg-1"
        sourceDurationSeconds={10}
        trimStartSeconds={1}
        trimEndSeconds={6}
      />,
    );
    const el = screen.getByTestId("segment-trim-editor");
    expect(el).toHaveAttribute("data-trim-start", "1");
    expect(el).toHaveAttribute("data-trim-end", "6");
    expect(screen.getByTestId("trim-effective-duration")).toHaveTextContent("5.0s");
  });

  it("emits a trim command on start-edge change without direct mutation", () => {
    const onCommand = vi.fn();
    render(
      <SegmentTrimEditor
        segmentId="seg-1"
        sourceDurationSeconds={10}
        trimStartSeconds={0}
        trimEndSeconds={10}
        onCommand={onCommand}
      />,
    );
    fireEvent.change(screen.getByTestId("trim-start-input"), { target: { value: "2" } });
    expect(onCommand).toHaveBeenCalledWith({
      type: "trimSegment",
      segmentId: "seg-1",
      trimStartSeconds: 2,
      trimEndSeconds: 10,
    });
  });

  it("does not emit a command for an invalid trim and shows an error", () => {
    const onCommand = vi.fn();
    render(
      <SegmentTrimEditor
        segmentId="seg-1"
        sourceDurationSeconds={10}
        trimStartSeconds={0}
        trimEndSeconds={10}
        onCommand={onCommand}
      />,
    );
    fireEvent.change(screen.getByTestId("trim-end-input"), { target: { value: "11" } });
    expect(onCommand).not.toHaveBeenCalled();
    expect(screen.getByTestId("segment-trim-editor")).toHaveAttribute("data-status", "error");
  });
});
