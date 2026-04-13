import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import ProgressDialog from "../components/creator/ProgressDialog";

// --------------- helpers ---------------

const API = "/api/creator";
const RUN_ID = 70;

function mockFetch(responses: Record<string, { status?: number; body: unknown }>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    for (const [pattern, resp] of Object.entries(responses)) {
      if (key.includes(pattern) || url.includes(pattern)) {
        return {
          ok: (resp.status ?? 200) < 400,
          status: resp.status ?? 200,
          json: async () => resp.body,
        };
      }
    }
    return { ok: false, status: 404, json: async () => ({ detail: "Not found" }) };
  }) as unknown as typeof fetch;
}

// --------------- tests ---------------

describe("ProgressDialog", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render when open=false", () => {
    globalThis.fetch = mockFetch({});
    render(
      <ProgressDialog
        open={false}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );
    expect(screen.queryByTestId("progress-dialog")).not.toBeInTheDocument();
  });

  it("renders overlay and dialog when open=true", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });
    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );

    // Initial render should show dialog immediately
    expect(screen.getByTestId("progress-dialog-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("progress-dialog")).toBeInTheDocument();

    // Wait for first poll to resolve
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-stage")).toBeInTheDocument();
    expect(screen.getByTestId("progress-status")).toHaveTextContent("Status: running");
  });

  it("shows friendly stage label for known stages", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "VISUAL_ASSET_GENERATING", status: "running" },
      },
    });
    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="VISUAL_ASSET_GENERATING"
        apiBase={API}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-stage")).toHaveTextContent(
      "Generating visual assets…",
    );
  });

  it("shows spinner while running", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });
    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-spinner")).toBeInTheDocument();
  });

  it("calls onComplete when stage transitions past expected", async () => {
    const onComplete = vi.fn();
    let callNum = 0;

    globalThis.fetch = vi.fn(async () => {
      callNum++;
      const stage = callNum <= 1 ? "SCRIPT_GENERATING" : "SCRIPT_REVIEW";
      return {
        ok: true,
        status: 200,
        json: async () => ({ current_stage: stage, status: "running" }),
      };
    }) as unknown as typeof fetch;

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        pollInterval={1000}
        onComplete={onComplete}
      />,
    );

    // First poll — still generating
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(onComplete).not.toHaveBeenCalled();

    // Second poll — moved to SCRIPT_REVIEW
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(onComplete).toHaveBeenCalledWith("SCRIPT_REVIEW", "running");
    expect(screen.getByTestId("progress-completed")).toHaveTextContent(
      "Generation complete",
    );
    // Spinner should be gone
    expect(screen.queryByTestId("progress-spinner")).not.toBeInTheDocument();
  });

  it("calls onFailed when run status becomes failed", async () => {
    const onFailed = vi.fn();
    let callNum = 0;

    globalThis.fetch = vi.fn(async () => {
      callNum++;
      const status = callNum <= 1 ? "running" : "failed";
      return {
        ok: true,
        status: 200,
        json: async () => ({ current_stage: "SCRIPT_GENERATING", status }),
      };
    }) as unknown as typeof fetch;

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        pollInterval={1000}
        onFailed={onFailed}
      />,
    );

    // First poll — running
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(onFailed).not.toHaveBeenCalled();

    // Second poll — failed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(onFailed).toHaveBeenCalledWith("SCRIPT_GENERATING", "failed");
    expect(screen.getByTestId("progress-failed")).toHaveTextContent("Generation failed");
  });

  it("shows error when poll request fails", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        status: 500,
        body: { detail: "Internal server error" },
      },
    });

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-error")).toHaveTextContent(
      "Internal server error",
    );
  });

  it("increments poll count on each successful poll", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        pollInterval={1000}
      />,
    );

    // First poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("progress-poll-count")).toHaveTextContent("1 poll");

    // Second poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId("progress-poll-count")).toHaveTextContent("2 polls");
  });

  it("calls onClose when dismiss/close button is clicked", async () => {
    const onClose = vi.fn();
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        onClose={onClose}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    fireEvent.click(screen.getByTestId("progress-close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("button says 'Dismiss' when running, 'Close' when terminal", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-close")).toHaveTextContent("Dismiss");
  });

  it("resets state when closed and reopened", async () => {
    const onComplete = vi.fn();
    let callNum = 0;

    globalThis.fetch = vi.fn(async () => {
      callNum++;
      // First 2 calls: still generating. Call 3+: review stage.
      const stage = callNum <= 2 ? "SCRIPT_GENERATING" : "SCRIPT_REVIEW";
      return {
        ok: true,
        status: 200,
        json: async () => ({ current_stage: stage, status: "running" }),
      };
    }) as unknown as typeof fetch;

    const { rerender } = render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        pollInterval={1000}
        onComplete={onComplete}
      />,
    );

    // First poll — still generating
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("progress-poll-count")).toHaveTextContent("1 poll");

    // Second poll — still generating
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId("progress-poll-count")).toHaveTextContent("2 polls");
    expect(onComplete).not.toHaveBeenCalled();

    // Close dialog
    await act(async () => {
      rerender(
        <ProgressDialog
          open={false}
          runId={RUN_ID}
          expectedStage="SCRIPT_GENERATING"
          apiBase={API}
          pollInterval={1000}
          onComplete={onComplete}
        />,
      );
    });
    expect(screen.queryByTestId("progress-dialog")).not.toBeInTheDocument();

    // Reopen — callNum=3 will return SCRIPT_REVIEW
    await act(async () => {
      rerender(
        <ProgressDialog
          open={true}
          runId={RUN_ID}
          expectedStage="SCRIPT_GENERATING"
          apiBase={API}
          pollInterval={1000}
          onComplete={onComplete}
        />,
      );
      // Allow the useEffect to schedule and the immediate poll to fire
      await vi.advanceTimersByTimeAsync(0);
    });

    // callNum=3 → SCRIPT_REVIEW → should trigger onComplete
    expect(onComplete).toHaveBeenCalledWith("SCRIPT_REVIEW", "running");
    // Poll count should have reset to 1 (not continuing from 2)
    expect(screen.getByTestId("progress-poll-count")).toHaveTextContent("1 poll");
  });

  it("stops polling after completion", async () => {
    let callNum = 0;
    globalThis.fetch = vi.fn(async () => {
      callNum++;
      const stage = callNum <= 1 ? "SCRIPT_GENERATING" : "SCRIPT_REVIEW";
      return {
        ok: true,
        status: 200,
        json: async () => ({ current_stage: stage, status: "running" }),
      };
    }) as unknown as typeof fetch;

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        pollInterval={1000}
      />,
    );

    // First poll — generating
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Second poll — complete
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByTestId("progress-completed")).toBeInTheDocument();

    const fetchCountAfterComplete = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length;

    // Advance time — no more polls should fire
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBe(
      fetchCountAfterComplete,
    );
  });

  it("handles network error gracefully", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new Error("Network failure");
    }) as unknown as typeof fetch;

    render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(screen.getByTestId("progress-error")).toHaveTextContent("Network failure");
  });
});

describe("ProgressDialog accessibility", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function renderOpen(overrides: Partial<{ onClose: () => void }> = {}) {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}`]: {
        body: { current_stage: "SCRIPT_GENERATING", status: "running" },
      },
    });
    return render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
        onClose={overrides.onClose}
      />,
    );
  }

  it('has role="dialog" and aria-modal="true"', async () => {
    renderOpen();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("has aria-labelledby pointing to the stage heading", async () => {
    renderOpen();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const dialog = screen.getByRole("dialog");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const titleEl = document.getElementById(labelId!);
    expect(titleEl).toHaveTextContent("Generating script");
  });

  it("has aria-describedby pointing to the status paragraph", async () => {
    renderOpen();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const dialog = screen.getByRole("dialog");
    const descAttr = dialog.getAttribute("aria-describedby");
    expect(descAttr).toBeTruthy();
    const descEl = document.getElementById(descAttr!);
    expect(descEl).toHaveTextContent("Status: running");
  });

  it("calls onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    renderOpen({ onClose });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps focus within dialog (Tab wraps around)", async () => {
    renderOpen();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const dialog = screen.getByTestId("progress-dialog");
    const buttons = dialog.querySelectorAll<HTMLElement>("button:not([disabled])");
    expect(buttons.length).toBeGreaterThanOrEqual(1);

    const last = buttons[buttons.length - 1];
    const first = buttons[0];
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });

  it("restores focus to previously focused element on close", async () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Open";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { rerender } = render(
      <ProgressDialog
        open={true}
        runId={RUN_ID}
        expectedStage="SCRIPT_GENERATING"
        apiBase={API}
      />,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(document.activeElement).not.toBe(trigger);

    await act(async () => {
      rerender(
        <ProgressDialog
          open={false}
          runId={RUN_ID}
          expectedStage="SCRIPT_GENERATING"
          apiBase={API}
        />,
      );
    });

    expect(document.activeElement).toBe(trigger);
    document.body.removeChild(trigger);
  });
});
