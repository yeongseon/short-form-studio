import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import StructuredScriptEditor from "../components/creator/StructuredScriptEditor";
import type { SectionData } from "../components/creator/StructuredScriptEditor";

// --------------- helpers ---------------

const API = "/api/creator";
const RUN_ID = 42;

function makeSections(n: number): SectionData[] {
  return Array.from({ length: n }, (_, i) => ({
    section_id: `sec-${i + 1}`,
    type: "narration",
    text: `Text for section ${i + 1}`,
    display_text: null,
    speaker: "host",
    duration: 5,
    visual_override: null,
  }));
}

const LOADED_DATA = {
  run_id: RUN_ID,
  sections: makeSections(3),
  version: 1,
};

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

describe("StructuredScriptEditor", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("shows loading state initially", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);
    expect(screen.getByTestId("structured-loading")).toHaveTextContent("Loading sections");
  });

  it("loads and renders section cards", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("structured-sections")).toBeInTheDocument();
    });

    expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    expect(screen.getByTestId("section-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("section-card-2")).toBeInTheDocument();
    expect(screen.getByTestId("structured-version")).toHaveTextContent("v1");
  });

  it("shows empty state when no sections", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: {
        body: { run_id: RUN_ID, sections: [], version: 1 },
      },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("structured-empty")).toBeInTheDocument();
    });
  });

  it("shows error when load fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: {
        status: 404,
        body: { detail: "No script draft found for this run" },
      },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("structured-error")).toHaveTextContent("No script draft found");
    });
    expect(onError).toHaveBeenCalledWith("load", "No script draft found for this run");
  });

  it("shows dirty indicator when section text is edited", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("structured-dirty")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("section-0-text"), {
      target: { value: "Modified text" },
    });

    expect(screen.getByTestId("structured-dirty")).toHaveTextContent("Unsaved changes");
  });

  it("enables save button only when dirty", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("structured-save-btn")).toBeInTheDocument();
    });

    expect(screen.getByTestId("structured-save-btn")).toBeDisabled();

    fireEvent.change(screen.getByTestId("section-0-text"), {
      target: { value: "Changed" },
    });

    expect(screen.getByTestId("structured-save-btn")).not.toBeDisabled();
  });

  it("reorders sections up", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-1")).toBeInTheDocument();
    });

    // Section 1 (index 1) should be moveable up
    fireEvent.click(screen.getByTestId("section-1-move-up"));

    // After move, section-card-0 should now contain "Text for section 2"
    const firstCardText = screen.getByTestId("section-0-text") as HTMLTextAreaElement;
    expect(firstCardText.value).toBe("Text for section 2");
  });

  it("reorders sections down", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("section-0-move-down"));

    const secondCardText = screen.getByTestId("section-1-text") as HTMLTextAreaElement;
    expect(secondCardText.value).toBe("Text for section 1");
  });

  it("disables move-up for first section and move-down for last", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    expect(screen.getByTestId("section-0-move-up")).toBeDisabled();
    expect(screen.getByTestId("section-2-move-down")).toBeDisabled();
  });

  it("saves sections and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const savedData = { run_id: RUN_ID, draft: { version: 2 } };
    globalThis.fetch = mockFetch({
      [`GET ${API}/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
      [`PUT ${API}/runs/${RUN_ID}/script/structured`]: { body: savedData },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} onSuccess={onSuccess} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("section-0-text"), {
      target: { value: "Updated text" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("structured-save-btn"));
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(savedData);
    });
    expect(screen.getByTestId("structured-version")).toHaveTextContent("v2");
    expect(screen.queryByTestId("structured-dirty")).not.toBeInTheDocument();
  });

  it("shows error when save fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetch({
      [`GET ${API}/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
      [`PUT ${API}/runs/${RUN_ID}/script/structured`]: { status: 400, body: { detail: "Invalid sections" } },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("section-0-text"), {
      target: { value: "Changed" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("structured-save-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("structured-error")).toHaveTextContent("Invalid sections");
    });
    expect(onError).toHaveBeenCalledWith("save", "Invalid sections");
  });

  it("hides buttons in readOnly mode", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} readOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("structured-save-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("section-0-move-up")).not.toBeInTheDocument();
    expect(screen.queryByTestId("section-0-move-down")).not.toBeInTheDocument();
  });

  it("renders section fields: type, speaker, text, display_text, duration", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    expect(screen.getByTestId("section-0-type")).toHaveValue("narration");
    expect(screen.getByTestId("section-0-speaker")).toHaveValue("host");
    expect(screen.getByTestId("section-0-text")).toHaveValue("Text for section 1");
    expect(screen.getByTestId("section-0-duration")).toHaveValue(5);
  });

  it("editing type field marks dirty", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/script/structured`]: { body: LOADED_DATA },
    });
    render(<StructuredScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("section-card-0")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("section-0-type"), {
      target: { value: "dialog" },
    });

    expect(screen.getByTestId("structured-dirty")).toBeInTheDocument();
  });
});
