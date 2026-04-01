import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ProjectPage from "../pages/ProjectPage";

// ---- mock data ----

const MOCK_PROJECT: {
  id: number;
  title: string | null;
  source_type: string;
  status: string;
  created_at: string;
  updated_at: string;
} = {
  id: 7,
  title: "My Short",
  source_type: "idea",
  status: "active",
  created_at: "2025-03-15T10:00:00Z",
  updated_at: "2025-03-15T12:00:00Z",
};

const MOCK_RUN_IDEA = {
  id: 1,
  project_id: 7,
  current_stage: "IDEA_READY",
  status: "pending",
  restart_from: null,
};

const MOCK_RUN_REVIEW = {
  id: 1,
  project_id: 7,
  current_stage: "SCRIPT_REVIEW",
  status: "running",
  restart_from: null,
};

const MOCK_RUN_VP_SETUP = {
  id: 1,
  project_id: 7,
  current_stage: "VISUAL_PLAN_SETUP",
  status: "running",
  restart_from: null,
};

const MOCK_RUN_GENERATING = {
  id: 1,
  project_id: 7,
  current_stage: "SCRIPT_GENERATING",
  status: "running",
  restart_from: null,
};

const MOCK_RUN_VP_GENERATING = {
  id: 1,
  project_id: 7,
  current_stage: "VISUAL_PLAN_GENERATING",
  status: "running",
  restart_from: null,
};

const MOCK_RUN_VP_REVIEW = {
  id: 1,
  project_id: 7,
  current_stage: "VISUAL_PLAN_REVIEW",
  status: "running",
  restart_from: null,
};

// ---- helpers ----

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderPage(projectId = "7") {
  return render(
    <MemoryRouter initialEntries={[`/projects/${projectId}`]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

type MockRun = typeof MOCK_RUN_IDEA;

function mockFetchProjectAndRuns(
  project: typeof MOCK_PROJECT | null,
  runs: MockRun[] = [],
) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : (input as Request).url;

    // GET /projects/:id/runs
    if (url.includes("/projects/") && url.includes("/runs")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ runs, total: runs.length }),
      } as Response);
    }
    // GET /projects/:id
    if (url.includes("/projects/")) {
      if (!project) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: () => Promise.resolve({ detail: "Project not found" }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(project),
      } as Response);
    }
    // GET /runs/:id (for refreshRun)
    // GET /runs/:id/visual-assets
    // GET /runs/:id/preview
    if (url.includes("/preview")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 1,
            current_stage: "FINAL_REVIEW",
            video: { id: 1, path: "data/artifacts/1/render/output.mp4", render_profile: "shorts_default" },
            audio: { id: 2, path: "data/artifacts/1/audio/audio.wav", model_used: "qwen3-tts" },
            subtitle: { id: 3, path: "data/artifacts/1/subtitles/subtitles.srt", format: "srt" },
          }),
      } as Response);
    }
    if (url.includes("/visual-assets")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ run_id: 1, scenes: {}, total_scenes: 0, total_assets: 0 }),
      } as Response);
    }
    // GET /api/creator/models
    if (url.includes("/models")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ script_models: [], image_models: [], tts_models: [], stt_models: [] }),
      } as Response);
    }
    // GET /runs/:id/storyboard
    if (url.includes("/storyboard")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 1,
            paragraphs: [
              {
                section_id: "sec-0",
                order: 0,
                text: "Test paragraph",
                display_text: null,
                image_prompt: "test prompt",
                image_url: null,
                audio_url: null,
                audio_duration: null,
                subtitles_url: null,
                subtitle_entries: null,
                status: "idle",
                stale_flags: null,
                scene_id: "scene-0",
                image_asset_id: null,
                audio_artifact_id: null,
                subtitle_artifact_id: null,
              },
            ],
            render_ready: false,
            total_paragraphs: 1,
            ready_paragraphs: 0,
          }),
      } as Response);
    }
    // GET /runs/:id (for refreshRun)
    if (url.includes("/runs/")) {
      const latestRun = runs[0];
      if (latestRun) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(latestRun),
        } as Response);
      }
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockNavigate.mockReset();
});

describe("ProjectPage", () => {
  // ---- Loading ----
  it("shows loading state initially", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Loading project");
  });

  // ---- Error ----
  it("shows error when project not found", async () => {
    mockFetchProjectAndRuns(null);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Project not found");
  });

  it("shows back link on error", async () => {
    mockFetchProjectAndRuns(null);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Back to projects")).toBeInTheDocument();
    });
  });

  // ---- Invalid project ID ----
  it("shows invalid ID message for non-numeric id", () => {
    render(
      <MemoryRouter initialEntries={["/projects/abc"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Invalid project ID.")).toBeInTheDocument();
  });

  // ---- Project loaded, no runs ----
  it("shows project title and no-run state", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, []);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("My Short")).toBeInTheDocument();
    });
    expect(screen.getByTestId("no-run")).toBeInTheDocument();
    expect(screen.getByText("No runs yet")).toBeInTheDocument();
  });

  it("shows source and status metadata", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, []);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Source: idea/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Status: active/)).toBeInTheDocument();
  });

  // ---- Project with run in IDEA_READY ----
  it("shows stepper and Generate Script button for IDEA_READY", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("My Short")).toBeInTheDocument();
    });
    // Stepper should be present (PipelineStepper renders step labels)
    expect(screen.getByText("Idea")).toBeInTheDocument();
    expect(screen.getByText("Script")).toBeInTheDocument();
    // Generate button visible
    expect(screen.getByRole("button", { name: "Generate Script" })).toBeInTheDocument();
    // Approve and Regenerate should not be visible
    expect(screen.queryByRole("button", { name: "Approve Script" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Regenerate Script" })).not.toBeInTheDocument();
  });

  // ---- Project with run in SCRIPT_REVIEW ----
  it("shows editor tabs and action buttons for SCRIPT_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("My Short")).toBeInTheDocument();
    });
    // Editor tabs
    expect(screen.getByRole("tab", { name: "Markdown" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Structured" })).toBeInTheDocument();
    // Approve + Regenerate Script  visible
    expect(screen.getByRole("button", { name: "Approve Script" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate Script" })).toBeInTheDocument();
  });

  it("switches between markdown and structured tabs", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: "Markdown" })).toBeInTheDocument();
    });

    // Default: Markdown tab selected
    const mdTab = screen.getByRole("tab", { name: "Markdown" });
    expect(mdTab.getAttribute("aria-selected")).toBe("true");

    // Switch to structured
    fireEvent.click(screen.getByRole("tab", { name: "Structured" }));
    await waitFor(() => {
      const stTab = screen.getByRole("tab", { name: "Structured" });
      expect(stTab.getAttribute("aria-selected")).toBe("true");
      expect(mdTab.getAttribute("aria-selected")).toBe("false");
    });
  });

  // ---- SCRIPT_GENERATING state ----
  it("shows generating indicator for SCRIPT_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("generating-indicator")).toBeInTheDocument();
    });
    expect(screen.getByText("Generating Script…")).toBeInTheDocument();
    // Editor tabs should NOT be visible during generation
    expect(screen.queryByRole("tab", { name: "Markdown" })).not.toBeInTheDocument();
  });

  // ---- Approve action ----
  it("calls approve endpoint and shows status", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Script" })).toBeInTheDocument();
    });

    // Override fetch for the approve call
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Approve Script" }));

    await waitFor(() => {
      // Verify approve endpoint was called
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/approve-script"))).toBe(true);
    });
  });

  // ---- Generate action ----
  it("calls generate endpoint on button click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Generate Script" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Generate Script" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/generate-script"))).toBe(true);
    });
  });

  // ---- Restart action ----
  it("calls restart endpoint on Regenerate click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Regenerate Script" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Regenerate Script" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/restart"))).toBe(true);
    });
  });

  // ---- API calls ----
  it("fetches project and runs on mount", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/runs")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ runs: [], total: 0 }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_PROJECT),
      } as Response);
    });

    renderPage();

    await waitFor(() => {
      const calls = spy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/projects/7") && !u.includes("/runs"))).toBe(true);
      expect(calls.some((u) => u.includes("/projects/7/runs"))).toBe(true);
    });
  });

  // ---- Untitled project ----
  it("shows 'Untitled Project' for null title", async () => {
    mockFetchProjectAndRuns({ ...MOCK_PROJECT, title: null as unknown as string }, []);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Untitled Project")).toBeInTheDocument();
    });
  });

  // ---- Back link ----
  it("renders back link to projects", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("← Projects")).toBeInTheDocument();
    });
  });

  // ---- Action error display ----
  it("shows error status when approve fails", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Script" })).toBeInTheDocument();
    });

    // Override fetch to fail on approve
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/approve-script")) {
        return Promise.resolve({
          ok: false,
          status: 409,
          json: () => Promise.resolve({ detail: "Stage conflict" }),
        } as Response);
      }
      // Fallback for other calls
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_RUN_REVIEW),
      } as Response);
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve Script" }));

    await waitFor(() => {
      expect(screen.getByText("Stage conflict")).toBeInTheDocument();
    });
  });
  // ---- Visual Plan stages ----

  it("shows VP generating indicator for VISUAL_PLAN_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("vp-generating-indicator")).toBeInTheDocument();
    });
    expect(screen.getByText("Generating Visual Plan\u2026")).toBeInTheDocument();
    // Script editor tabs should NOT be visible
    expect(screen.queryByRole("tab", { name: "Markdown" })).not.toBeInTheDocument();
  });

  it("shows VisualPlanEditor and action buttons for VISUAL_PLAN_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("visual-plan-editor")).toBeInTheDocument();
    });
    // Approve and Regenerate Plan visible
    expect(screen.getByRole("button", { name: "Approve Visual Plan" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate Plan" })).toBeInTheDocument();
    // Script actions should not be visible
    expect(screen.queryByRole("button", { name: "Approve Script" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Script" })).not.toBeInTheDocument();
  });

  it("calls approve-visual-plan endpoint on Approve Visual Plan click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Visual Plan" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Approve Visual Plan" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/approve-visual-plan"))).toBe(true);
    });
  });

  it("shows Generate Visual Plan button in VISUAL_PLAN_SETUP", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_SETUP]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Generate Visual Plan" })).toBeInTheDocument();
    });
  });

  it("calls generate-visual-plan endpoint from VISUAL_PLAN_SETUP", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_SETUP]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Generate Visual Plan" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Generate Visual Plan" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/generate-visual-plan"))).toBe(true);
    });
  });

  it("calls restart with VISUAL_PLAN_GENERATING stage on Regenerate Plan click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Regenerate Plan" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByRole("button", { name: "Regenerate Plan" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls;
      const restartCall = calls.find(([url]) => {
        const u = typeof url === "string" ? url : (url as Request).url;
        return u.includes("/restart");
      });
      expect(restartCall).toBeDefined();
      const body = JSON.parse(restartCall![1]!.body as string);
      expect(body.stage).toBe("VISUAL_PLAN_GENERATING");
    });
  });

  // ---- Visual Asset Stages ----

  const MOCK_RUN_VA_GENERATING = {
    id: 1,
    project_id: 7,
    current_stage: "VISUAL_ASSET_GENERATING",
    status: "running",
    restart_from: null,
  };

  const MOCK_RUN_VA_REVIEW = {
    id: 1,
    project_id: 7,
    current_stage: "VISUAL_ASSET_REVIEW",
    status: "running",
    restart_from: null,
  };

  const MOCK_RUN_AUDIO_GENERATING = {
    id: 1,
    project_id: 7,
    current_stage: "AUDIO_GENERATING",
    status: "running",
    restart_from: null,
  };

  const MOCK_RUN_SUBTITLE_GENERATING = {
    id: 1,
    project_id: 7,
    current_stage: "SUBTITLE_GENERATING",
    status: "running",
    restart_from: null,
  };

  const MOCK_RUN_RENDER_GENERATING = {
    id: 1,
    project_id: 7,
    current_stage: "RENDER_GENERATING",
    status: "running",
    restart_from: null,
  };

  const MOCK_RUN_FINAL_REVIEW = {
    id: 1,
    project_id: 7,
    current_stage: "FINAL_REVIEW",
    status: "running",
    restart_from: null,
  };

  it("shows VA generating indicator for VISUAL_ASSET_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("va-generating-indicator")).toBeInTheDocument();
    });
    expect(screen.getByText("Generating Visual Assets…")).toBeInTheDocument();
  });

  it("shows visual-asset-section for VISUAL_ASSET_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("visual-asset-section")).toBeInTheDocument();
    });
  });

  it("shows scene regen controls in VISUAL_ASSET_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("scene-regen-controls")).toBeInTheDocument();
    });
    expect(screen.getByTestId("scene-id-input")).toBeInTheDocument();
    expect(screen.getByTestId("regen-scene-btn")).toBeInTheDocument();
    expect(screen.getByTestId("generate-scene-btn")).toBeInTheDocument();
  });

  it("hides scene regen controls during VISUAL_ASSET_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("visual-asset-section")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("scene-regen-controls")).not.toBeInTheDocument();
  });

  it("shows Approve Assets button in VISUAL_ASSET_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Assets" })).toBeInTheDocument();
    });
  });

  it("calls approve-visual-assets endpoint on Approve Assets click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Assets" })).toBeInTheDocument();
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByRole("button", { name: "Approve Assets" }));
    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/approve-visual-assets"))).toBe(true);
    });
  });

  it("calls generate-visual-assets endpoint on Regenerate All click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Regenerate All" })).toBeInTheDocument();
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate All" }));
    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/generate-visual-assets"))).toBe(true);
    });
  });

  it("calls restart with VISUAL_ASSET_GENERATING stage on Restart Assets click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Restart Assets" })).toBeInTheDocument();
    });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByRole("button", { name: "Restart Assets" }));
    await waitFor(() => {
      const calls = fetchSpy.mock.calls;
      const restartCall = calls.find(([url]) => {
        const u = typeof url === "string" ? url : (url as Request).url;
        return u.includes("/restart");
      });
      expect(restartCall).toBeDefined();
      const body = JSON.parse(restartCall![1]!.body as string);
      expect(body.stage).toBe("VISUAL_ASSET_GENERATING");
    });
  });

  it("calls regenerate-image endpoint when scene regen button clicked", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("scene-regen-controls")).toBeInTheDocument();
    });
    const input = screen.getByTestId("scene-id-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "scene-0" } });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByTestId("regen-scene-btn"));
    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/scenes/scene-0/regenerate-image"))).toBe(true);
    });
  });

  it("calls generate-image endpoint when generate-scene button clicked", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("scene-regen-controls")).toBeInTheDocument();
    });
    const input = screen.getByTestId("scene-id-input") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "scene-1" } });
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByTestId("generate-scene-btn"));
    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/scenes/scene-1/generate-image"))).toBe(true);
    });
  });

  // ---- Audio / Subtitle / Render / Final Review Stages ----

  it("shows storyboard view for AUDIO_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-view")).toBeInTheDocument();
    });
    // Render should not be offered before subtitle stage
    expect(screen.queryByRole("button", { name: "Render Video" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restart from Script" })).toBeInTheDocument();
  });

  it("shows storyboard view for SUBTITLE_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_SUBTITLE_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-view")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Render Video" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Render Profile/)).toBeInTheDocument();
  });

  it("shows storyboard view for RENDER_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_RENDER_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-view")).toBeInTheDocument();
    });
    // During render, storyboard should be read-only (no generate buttons in storyboard)
    expect(screen.getByRole("button", { name: "Restart from Script" })).toBeInTheDocument();
  });

  it("shows final review section with storyboard and review link for FINAL_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_FINAL_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-view")).toBeInTheDocument();
    });
    expect(screen.getByTestId("final-review-section")).toBeInTheDocument();
    expect(screen.getByText("Pipeline Complete")).toBeInTheDocument();
    expect(screen.getByTestId("review-link")).toBeInTheDocument();
    expect(screen.getByTestId("review-link").getAttribute("href")).toBe("/review/1");
  });

  it("shows Restart from Script button in FINAL_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_FINAL_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Restart from Script" })).toBeInTheDocument();
    });
  });

  it("hides approve button during AUDIO_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("storyboard-view")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("hides idea-only go-back action for markdown-source script review", async () => {
    mockFetchProjectAndRuns({ ...MOCK_PROJECT, source_type: "markdown" }, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Approve Script" })).toBeInTheDocument();
    });
    expect(screen.queryByTestId("go-back-btn")).not.toBeInTheDocument();
  });

  it("uses selected render profile when rendering from subtitle stage", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_SUBTITLE_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Render Video" })).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.change(screen.getByLabelText(/Render Profile/), { target: { value: "high_quality" } });
    fireEvent.click(screen.getByRole("button", { name: "Render Video" }));

    await waitFor(() => {
      const renderCall = fetchSpy.mock.calls.find(([url]) =>
        (typeof url === "string" ? url : (url as Request).url).includes("/render")
      );
      expect(renderCall).toBeTruthy();
      const body = JSON.parse((renderCall![1] as RequestInit).body as string);
      expect(body.render_profile).toBe("high_quality");
    });
  });
});
