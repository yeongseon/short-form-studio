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
  idea_brief?: string | null;
  latest_run?: { run_id: number; current_stage: string | null; status: string | null } | null;
  created_at: string;
  updated_at: string;
} = {
  id: 7,
  title: "My Short",
  source_type: "idea",
  status: "active",
  idea_brief: "A cool idea",
  latest_run: { run_id: 1, current_stage: "IDEA_READY", status: "pending" },
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

// ---- helpers ----

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderPage(projectId = "7") {
  return render(
    <MemoryRouter
      initialEntries={[`/projects/${projectId}`]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
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
    if (url.includes("/projects/") && !url.includes("/runs")) {
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
    // GET /runs/:id/preview
    if (url.includes("/preview")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: 1,
            current_stage: "FINAL_REVIEW",
            video: {
              id: 1,
              path: "data/artifacts/1/render/output.mp4",
              render_profile: "shorts_default",
            },
            audio: { id: 2, path: "data/artifacts/1/audio/audio.wav" },
            subtitle: { id: 3, path: "data/artifacts/1/subtitles/subtitles.srt" },
          }),
      } as Response);
    }
    // GET /api/creator/models
    if (url.includes("/models")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            script_models: [],
            image_models: [],
            tts_models: [],
            stt_models: [],
          }),
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
    // GET /runs/:id/script/structured
    if (url.includes("/script/structured")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ sections: [] }),
      } as Response);
    }
    // GET /runs/:id/script/markdown
    if (url.includes("/script/markdown")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ markdown: "# Test Script" }),
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
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
    } as Response);
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockNavigate.mockReset();
});

describe("ProjectPage", () => {
  // ═══════════════ Loading / Error / Edge Cases ═══════════════

  it("shows loading state initially", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Loading project");
  });

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

  it("shows invalid ID message for non-numeric id", () => {
    render(
      <MemoryRouter
        initialEntries={["/projects/abc"]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("Invalid project ID.")).toBeInTheDocument();
  });

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

  it("shows run status and stage metadata when a run exists", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Status: running/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Stage: SCRIPT_REVIEW/)).toBeInTheDocument();
  });

  it("shows 'Untitled Project' for null title", async () => {
    mockFetchProjectAndRuns(
      { ...MOCK_PROJECT, title: null as unknown as string },
      [],
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Untitled Project")).toBeInTheDocument();
    });
  });

  it("renders back link to projects", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/Projects/)).toBeInTheDocument();
    });
  });

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
      expect(
        calls.some((u) => u.includes("/projects/7") && !u.includes("/runs")),
      ).toBe(true);
      expect(calls.some((u) => u.includes("/projects/7/runs"))).toBe(true);
    });
  });

  // ═══════════════ Script Stages (via ScriptComposer) ═══════════════

  it("renders ScriptComposer for IDEA_READY with Generate button", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("script-composer")).toBeInTheDocument();
    });
    // Stepper visible
    expect(screen.getByText("Idea")).toBeInTheDocument();
    expect(screen.getByText("Script")).toBeInTheDocument();
    // Generate Script button visible
    expect(
      screen.getByRole("button", { name: "Generate Script" }),
    ).toBeInTheDocument();
  });

  it("shows editor tabs for SCRIPT_REVIEW via ScriptComposer", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("script-composer")).toBeInTheDocument();
    });
    // Editor tabs
    expect(screen.getByRole("tab", { name: "Markdown" })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Structured" }),
    ).toBeInTheDocument();
    // Confirm + Regenerate buttons visible (ScriptComposer labels)
    expect(
      screen.getByRole("button", {
        name: "Confirm & Generate Visual Plan",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Regenerate" }),
    ).toBeInTheDocument();
  });

  it("switches between markdown and structured tabs", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("tab", { name: "Markdown" }),
      ).toBeInTheDocument();
    });

    const mdTab = screen.getByRole("tab", { name: "Markdown" });
    expect(mdTab.getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByRole("tab", { name: "Structured" }));
    await waitFor(() => {
      const stTab = screen.getByRole("tab", { name: "Structured" });
      expect(stTab.getAttribute("aria-selected")).toBe("true");
      expect(mdTab.getAttribute("aria-selected")).toBe("false");
    });
  });

  it("shows generating indicator for SCRIPT_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("script-generating-indicator"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/Generating Script/i)).toBeInTheDocument();
  });

  it("calls generate-script endpoint on Generate Script click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Generate Script" }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(
      screen.getByRole("button", { name: "Generate Script" }),
    );

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/generate-script"))).toBe(true);
    });
  });

  it("calls approve-script endpoint on Confirm click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "Confirm & Generate Visual Plan",
        }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm & Generate Visual Plan",
      }),
    );

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/approve-script"))).toBe(true);
    });
  });

  it("calls restart endpoint on Regenerate click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Regenerate" }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(screen.getByRole("button", { name: "Regenerate" }));

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/restart"))).toBe(true);
    });
  });

  it("shows error status when approve fails", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", {
          name: "Confirm & Generate Visual Plan",
        }),
      ).toBeInTheDocument();
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
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_RUN_REVIEW),
      } as Response);
    });

    fireEvent.click(
      screen.getByRole("button", {
        name: "Confirm & Generate Visual Plan",
      }),
    );

    await waitFor(() => {
      expect(screen.getByTestId("status-toast")).toHaveTextContent(
        "Stage conflict",
      );
    });
  });

  // ═══════════════ Visual Plan Stages ═══════════════

  it("shows VP generating indicator for VISUAL_PLAN_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("vp-generating-indicator"),
      ).toBeInTheDocument();
    });
    expect(screen.getByText(/Generating Visual Plan/i)).toBeInTheDocument();
    expect(screen.getByText("Visual Plan Setup")).toBeInTheDocument();
  });

  it("shows VisualPlanEditor and action buttons for VISUAL_PLAN_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("visual-plan-editor"),
      ).toBeInTheDocument();
    });
    expect(
      screen.getByRole("button", { name: "Approve Visual Plan" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Regenerate Plan" }),
    ).toBeInTheDocument();
  });

  it("calls approve-visual-plan endpoint on Approve Visual Plan click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Approve Visual Plan" }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(
      screen.getByRole("button", { name: "Approve Visual Plan" }),
    );

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/approve-visual-plan"))).toBe(
        true,
      );
    });
  });

  it("shows Generate Visual Plan button in VISUAL_PLAN_SETUP", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_SETUP]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Generate Visual Plan" }),
      ).toBeInTheDocument();
    });
  });

  it("calls generate-visual-plan endpoint from VISUAL_PLAN_SETUP", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_SETUP]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Generate Visual Plan" }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(
      screen.getByRole("button", { name: "Generate Visual Plan" }),
    );

    await waitFor(() => {
      const calls = fetchSpy.mock.calls.map(([url]) =>
        typeof url === "string" ? url : (url as Request).url,
      );
      expect(calls.some((u) => u.includes("/generate-visual-plan"))).toBe(
        true,
      );
    });
  });

  it("calls restart with VISUAL_PLAN_GENERATING stage on Regenerate Plan click", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Regenerate Plan" }),
      ).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    fireEvent.click(
      screen.getByRole("button", { name: "Regenerate Plan" }),
    );

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

  // ═══════════════ Storyboard Workspace Stages ═══════════════

  it("renders StoryboardWorkspace for VISUAL_ASSET_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
  });

  it("renders StoryboardWorkspace for VISUAL_ASSET_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VA_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
  });

  it("renders StoryboardWorkspace for AUDIO_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
  });

  it("renders StoryboardWorkspace for SUBTITLE_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_SUBTITLE_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
  });

  it("renders StoryboardWorkspace for RENDER_GENERATING", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_RENDER_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
  });

  it("shows final review section with review link for FINAL_REVIEW", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_FINAL_REVIEW]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
    expect(screen.getByTestId("final-review-section")).toBeInTheDocument();
    expect(screen.getByText("Pipeline Complete")).toBeInTheDocument();
    expect(screen.getByTestId("review-link")).toBeInTheDocument();
    expect(screen.getByTestId("review-link").getAttribute("href")).toBe(
      "/review/1",
    );
  });

  it("shows scene cards inside StoryboardWorkspace", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
    // The storyboard workspace should render a scene card for sec-0
    await waitFor(() => {
      expect(screen.getByTestId("scene-card-sec-0")).toBeInTheDocument();
    });
  });

  it("shows pipeline overview bar in StoryboardWorkspace", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("pipeline-overview-bar"),
      ).toBeInTheDocument();
    });
  });

  it("shows bulk action bar in StoryboardWorkspace", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("bulk-action-bar")).toBeInTheDocument();
    });
  });

  // ═══════════════ Go-Back Navigation ═══════════════

  it("shows go-back button for VISUAL_PLAN_SETUP", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_VP_SETUP]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("go-back-btn")).toBeInTheDocument();
    });
    expect(screen.getByTestId("go-back-btn")).toHaveTextContent(
      "Back to Script Review",
    );
  });

  it("hides go-back for markdown-source SCRIPT_REVIEW", async () => {
    mockFetchProjectAndRuns(
      { ...MOCK_PROJECT, source_type: "markdown" },
      [MOCK_RUN_REVIEW],
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("script-composer")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("go-back-btn")).not.toBeInTheDocument();
  });

  // ═══════════════ Stop / Resume / Delete ═══════════════

  it("shows Stop button for running run", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [
      { ...MOCK_RUN_IDEA, status: "running" },
    ]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Stop/ }),
      ).toBeInTheDocument();
    });
  });

  it("shows Resume button for cancelled run", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [
      { ...MOCK_RUN_IDEA, status: "cancelled" },
    ]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Resume/ }),
      ).toBeInTheDocument();
    });
  });

  it("shows Delete Project button", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    renderPage();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Delete Project/ }),
      ).toBeInTheDocument();
    });
  });

  // ═══════════════ Max Width ═══════════════

  it("uses wider max-width for storyboard stages", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_AUDIO_GENERATING]);
    const { container } = renderPage();
    await waitFor(() => {
      expect(
        screen.getByTestId("storyboard-workspace"),
      ).toBeInTheDocument();
    });
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.style.maxWidth).toBe("1200px");
  });

  it("uses narrower max-width for script stages", async () => {
    mockFetchProjectAndRuns(MOCK_PROJECT, [MOCK_RUN_IDEA]);
    const { container } = renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("script-composer")).toBeInTheDocument();
    });
    const wrapper = container.firstElementChild as HTMLElement;
    expect(wrapper.style.maxWidth).toBe("960px");
  });
});
