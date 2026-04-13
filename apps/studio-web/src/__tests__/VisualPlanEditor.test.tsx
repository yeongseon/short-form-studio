import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import VisualPlanEditor from "../components/creator/VisualPlanEditor";
import type { SceneData } from "../components/creator/VisualPlanEditor";

// --------------- helpers ---------------

const API = "/api/creator";
const RUN_ID = 42;

function makeScenes(n: number): SceneData[] {
  return Array.from({ length: n }, (_, i) => ({
    scene_id: `scene-${i + 1}`,
    section_id: `sec-${i + 1}`,
    scene_index: i,
    section_type: "narration",
    original_text: `Original text for scene ${i + 1}`,
    prompt: `A cinematic shot of scene ${i + 1}`,
    prompt_edited: false,
    prompt_source: "auto_generated" as const,
    style_tags: ["cinematic", "dramatic"],
    mood: "intense",
    composition: "wide shot",
    generation_status: "pending" as const,
    latest_asset_id: null,
  }));
}

const LOADED_DATA = {
  run_id: RUN_ID,
  scenes: makeScenes(3),
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

describe("VisualPlanEditor", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("shows loading state initially", () => {
    globalThis.fetch = vi.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);
    expect(screen.getByTestId("visual-plan-loading")).toHaveTextContent("Loading visual plan");
  });

  it("loads and renders scene cards", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-scenes")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    expect(screen.getByTestId("scene-scene-2")).toBeInTheDocument();
    expect(screen.getByTestId("scene-scene-3")).toBeInTheDocument();
    expect(screen.getByTestId("visual-plan-version")).toHaveTextContent("v1");
  });

  it("shows empty state when no scenes", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: {
        body: { run_id: RUN_ID, scenes: [], version: 1 },
      },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-empty")).toBeInTheDocument();
    });
  });

  it("shows error when load fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: {
        status: 404,
        body: { detail: "No active visual plan for run 42" },
      },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-error")).toHaveTextContent(
        "No active visual plan for run 42",
      );
    });
    expect(onError).toHaveBeenCalledWith("load", "No active visual plan for run 42");
  });

  it("editing prompt marks scene dirty", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("scene-scene-1-dirty")).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId("scene-scene-1-prompt"), {
      target: { value: "A modified prompt" },
    });

    expect(screen.getByTestId("scene-scene-1-dirty")).toHaveTextContent("Unsaved changes");
  });

  it("save button disabled when scene is clean", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scene-scene-1-save")).toBeDisabled();

    fireEvent.change(screen.getByTestId("scene-scene-1-prompt"), {
      target: { value: "Changed prompt" },
    });

    expect(screen.getByTestId("scene-scene-1-save")).not.toBeDisabled();
  });

  it("saves scene via PATCH with diff and calls onSuccess", async () => {
    const onSuccess = vi.fn();
    const updatedScenes = makeScenes(3);
    updatedScenes[0] = {
      ...updatedScenes[0],
      prompt: "Updated prompt",
      prompt_edited: true,
      prompt_source: "user_edited",
    };
    const savedData = { run_id: RUN_ID, version: 2, scenes: updatedScenes };

    globalThis.fetch = mockFetch({
      [`GET ${API}/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
      [`PATCH ${API}/runs/${RUN_ID}/visual-plan/scenes/scene-1`]: { body: savedData },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} onSuccess={onSuccess} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("scene-scene-1-prompt"), {
      target: { value: "Updated prompt" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("scene-scene-1-save"));
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(savedData);
    });

    // Verify PATCH was called with expected payload
    const patchCall = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.find(
      (call: unknown[]) => {
        const url = call[0] as string;
        const init = call[1] as RequestInit | undefined;
        return url.includes("scenes/scene-1") && init?.method === "PATCH";
      },
    );
    expect(patchCall).toBeDefined();
    const body = JSON.parse(patchCall![1].body as string);
    expect(body.prompt).toBe("Updated prompt");
    expect(body.prompt_edited).toBe(true);
    expect(body.prompt_source).toBe("user_edited");
    expect(body.expected_version).toBe(1);

    // Version updated and dirty cleared
    expect(screen.getByTestId("visual-plan-version")).toHaveTextContent("v2");
    expect(screen.queryByTestId("scene-scene-1-dirty")).not.toBeInTheDocument();
  });

  it("shows error when save fails", async () => {
    const onError = vi.fn();
    globalThis.fetch = mockFetch({
      [`GET ${API}/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
      [`PATCH ${API}/runs/${RUN_ID}/visual-plan/scenes/scene-1`]: {
        status: 409,
        body: { detail: "Version conflict" },
      },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} onError={onError} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("scene-scene-1-prompt"), {
      target: { value: "Changed" },
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("scene-scene-1-save"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-error")).toHaveTextContent("Version conflict");
    });
    expect(onError).toHaveBeenCalledWith("save", "Version conflict");
  });

  it("readOnly mode hides save buttons and disables editing", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} readOnly />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    // Save button not rendered in readOnly
    expect(screen.queryByTestId("scene-scene-1-save")).not.toBeInTheDocument();

    // Prompt textarea is readOnly
    const promptInput = screen.getByTestId("scene-scene-1-prompt") as HTMLTextAreaElement;
    expect(promptInput.readOnly).toBe(true);

    // Mood input is readOnly
    const moodInput = screen.getByTestId("scene-scene-1-mood") as HTMLInputElement;
    expect(moodInput.readOnly).toBe(true);
  });

  it("regenerate button is disabled (Phase 4)", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scene-scene-1-regenerate")).toBeDisabled();
  });

  it("renders scene fields: original_text, status, mood, composition, style_tags", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    expect(screen.getByTestId("scene-scene-1-original-text")).toHaveTextContent(
      "Original text for scene 1",
    );
    expect(screen.getByTestId("scene-scene-1-status")).toHaveTextContent("pending");

    const promptInput = screen.getByTestId("scene-scene-1-prompt") as HTMLTextAreaElement;
    expect(promptInput.value).toBe("A cinematic shot of scene 1");

    const moodInput = screen.getByTestId("scene-scene-1-mood") as HTMLInputElement;
    expect(moodInput.value).toBe("intense");

    const compInput = screen.getByTestId("scene-scene-1-composition") as HTMLInputElement;
    expect(compInput.value).toBe("wide shot");

    const tagsInput = screen.getByTestId("scene-scene-1-style-tags") as HTMLInputElement;
    expect(tagsInput.value).toBe("cinematic, dramatic");
  });

  it("editing mood marks scene dirty", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("scene-scene-1")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("scene-scene-1-mood"), {
      target: { value: "calm" },
    });

    expect(screen.getByTestId("scene-scene-1-dirty")).toBeInTheDocument();
  });

  it("displays scene count", async () => {
    globalThis.fetch = mockFetch({
      [`/runs/${RUN_ID}/visual-plan`]: { body: LOADED_DATA },
    });
    render(<VisualPlanEditor runId={RUN_ID} apiBase={API} />);

    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-scenes")).toBeInTheDocument();
    });

    // 3 scenes text
    expect(screen.getByText("3 scenes")).toBeInTheDocument();
  });
});
