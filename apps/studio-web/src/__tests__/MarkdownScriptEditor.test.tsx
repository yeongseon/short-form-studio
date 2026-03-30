import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import MarkdownScriptEditor from "../components/creator/MarkdownScriptEditor";

// --------------- fetch mock helpers ---------------

function mockFetchSuccess(responses: Record<string, { status?: number; body: unknown }>) {
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

// --------------- constants ---------------

const API = "/api/creator";
const RUN_ID = 42;
const LOAD_URL = `/runs/${RUN_ID}/script/markdown`;

const LOADED_DATA = {
  run_id: RUN_ID,
  markdown: "# Hello\n\nWorld",
  version: 1,
};

// --------------- tests ---------------

describe("MarkdownScriptEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows loading state initially", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);
    expect(screen.getByTestId("markdown-loading")).toHaveTextContent("Loading script");
  });

  it("loads and displays markdown content", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toHaveValue("# Hello\n\nWorld");
    });
    expect(screen.getByTestId("markdown-version")).toHaveTextContent("v1");
  });

  it("shows error when load fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetchSuccess({
      [LOAD_URL]: { status: 404, body: { detail: "No script draft found for this run" } },
    });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-error")).toHaveTextContent("No script draft found");
    });
    expect(onError).toHaveBeenCalledWith("load", "No script draft found for this run");
  });

  it("shows 'Unsaved changes' when content is modified", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toHaveValue("# Hello\n\nWorld");
    });

    expect(screen.queryByTestId("markdown-dirty")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "# Modified" },
    });

    expect(screen.getByTestId("markdown-dirty")).toHaveTextContent("Unsaved changes");
  });

  it("enables save button only when dirty", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    expect(screen.getByTestId("markdown-save-btn")).toBeDisabled();

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "New content" },
    });

    expect(screen.getByTestId("markdown-save-btn")).not.toBeDisabled();
  });

  it("saves markdown and updates version", async () => {
    const onSuccess = vi.fn();
    const savedData = { run_id: RUN_ID, draft: { version: 2 } };
    globalThis.fetch = mockFetchSuccess({
      [`GET ${API}/runs/${RUN_ID}/script/markdown`]: { body: LOADED_DATA },
      [`PUT ${API}/runs/${RUN_ID}/script/markdown`]: { body: savedData },
    });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} onSuccess={onSuccess} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toHaveValue("# Hello\n\nWorld");
    });

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "# Updated" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("markdown-save-btn"));
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith("save", savedData);
    });
    expect(screen.getByTestId("markdown-version")).toHaveTextContent("v2");
    // Dirty indicator should be gone after save
    expect(screen.queryByTestId("markdown-dirty")).not.toBeInTheDocument();
  });

  it("shows error when save fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetchSuccess({
      [`GET ${API}/runs/${RUN_ID}/script/markdown`]: { body: LOADED_DATA },
      [`PUT ${API}/runs/${RUN_ID}/script/markdown`]: { status: 400, body: { detail: "Bad request" } },
    });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "Modified" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("markdown-save-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("markdown-error")).toHaveTextContent("Bad request");
    });
    expect(onError).toHaveBeenCalledWith("save", "Bad request");
  });

  it("parses markdown and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const parseResult = {
      run_id: RUN_ID,
      sections: [{ type: "narration", text: "Hello" }],
      version: 2,
    };
    globalThis.fetch = mockFetchSuccess({
      [`GET ${API}/runs/${RUN_ID}/script/markdown`]: { body: LOADED_DATA },
      [`POST ${API}/runs/${RUN_ID}/script/parse-markdown`]: { body: parseResult },
    });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} onSuccess={onSuccess} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("markdown-parse-btn"));
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith("parse", parseResult);
    });
  });

  it("disables parse button when content is dirty", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    // Parse should be enabled when not dirty
    expect(screen.getByTestId("markdown-parse-btn")).not.toBeDisabled();

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "Dirty content" },
    });

    // Parse should be disabled when dirty (save first)
    expect(screen.getByTestId("markdown-parse-btn")).toBeDisabled();
  });

  it("shows error when parse fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetchSuccess({
      [`GET ${API}/runs/${RUN_ID}/script/markdown`]: { body: LOADED_DATA },
      [`POST ${API}/runs/${RUN_ID}/script/parse-markdown`]: {
        status: 400,
        body: { detail: "Draft has no markdown content to parse" },
      },
    });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("markdown-parse-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("markdown-error")).toHaveTextContent(
        "Draft has no markdown content to parse",
      );
    });
    expect(onError).toHaveBeenCalledWith("parse", "Draft has no markdown content to parse");
  });

  it("does not show save/parse buttons in readOnly mode", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} readOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("markdown-save-btn")).not.toBeInTheDocument();
    expect(screen.queryByTestId("markdown-parse-btn")).not.toBeInTheDocument();
    expect(screen.getByTestId("markdown-textarea")).toHaveAttribute("readonly");
  });

  it("disables textarea while saving", async () => {
    let resolveSave: (value: unknown) => void;
    globalThis.fetch = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        return new Promise((resolve) => {
          resolveSave = () =>
            resolve({
              ok: true,
              status: 200,
              json: async () => ({ run_id: RUN_ID, draft: { version: 2 } }),
            });
        });
      }
      return { ok: true, status: 200, json: async () => LOADED_DATA };
    }) as unknown as typeof fetch;

    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toHaveValue("# Hello\n\nWorld");
    });

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "Modified" },
    });

    // Start save — don't resolve yet
    await act(async () => {
      fireEvent.click(screen.getByTestId("markdown-save-btn"));
    });

    expect(screen.getByTestId("markdown-textarea")).toBeDisabled();
    expect(screen.getByTestId("markdown-save-btn")).toHaveTextContent("Saving…");

    // Resolve save
    await act(async () => {
      resolveSave!(undefined);
    });

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).not.toBeDisabled();
    });
  });

  it("does not save when markdown is empty/whitespace", async () => {
    globalThis.fetch = mockFetchSuccess({ [LOAD_URL]: { body: LOADED_DATA } });
    render(<MarkdownScriptEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("markdown-textarea")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("markdown-textarea"), {
      target: { value: "   " },
    });

    // Button should be disabled (dirty but whitespace-only)
    expect(screen.getByTestId("markdown-save-btn")).toBeDisabled();
  });
});
