import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ReviewPage from "../pages/ReviewPage";

// ---- mock data ----

const MOCK_RUN_FINAL_REVIEW = {
  id: 10,
  project_id: 5,
  current_stage: "FINAL_REVIEW",
  status: "running",
  restart_from: null,
};

const MOCK_RUN_IDEA_READY = {
  id: 11,
  project_id: 5,
  current_stage: "IDEA_READY",
  status: "pending",
  restart_from: null,
};

const MOCK_SCRIPT = {
  script: "# Scene 1\nA calm morning in Tokyo.",
  structured_script: null,
};

const MOCK_SCENES = {
  scenes: [
    { scene_id: "scene-0", description: "Tokyo skyline", image_prompt: "panoramic tokyo" },
    { scene_id: "scene-1", description: "Cherry blossoms", image_prompt: "sakura trees" },
  ],
};

const MOCK_ASSETS = {
  "scene-0": [
    { asset_path: "data/artifacts/10/visual/scene-0.png", model_used: "sd15", is_active: true },
  ],
  "scene-1": [
    { asset_path: "data/artifacts/10/visual/scene-1.png", model_used: "sd15", is_active: true },
  ],
};

const MOCK_PREVIEW = {
  run_id: 10,
  current_stage: "FINAL_REVIEW",
  video: {
    id: 1,
    path: "data/artifacts/10/render/output.mp4",
    render_profile: "shorts_default",
    created_at: "2026-03-31T10:00:00Z",
  },
  audio: {
    id: 2,
    path: "data/artifacts/10/audio/audio.wav",
    model_used: "qwen3-tts",
    created_at: "2026-03-31T09:00:00Z",
  },
  subtitle: {
    id: 3,
    path: "data/artifacts/10/subtitles/subtitles.srt",
    format: "srt",
    created_at: "2026-03-31T09:30:00Z",
  },
};

// ---- helpers ----

function renderPage(runId = "10") {
  return render(
    <MemoryRouter initialEntries={[`/review/${runId}`]}>
      <Routes>
        <Route path="/review/:runId" element={<ReviewPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockFetchAll(
  run: typeof MOCK_RUN_FINAL_REVIEW | null,
  opts: {
    script?: typeof MOCK_SCRIPT | null;
    scenes?: typeof MOCK_SCENES | null;
    assets?: typeof MOCK_ASSETS | null;
    preview?: typeof MOCK_PREVIEW | null;
  } = {},
) {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : (input as Request).url;

    // GET /runs/:id/preview
    if (url.includes("/preview")) {
      if (!opts.preview) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(opts.preview) } as Response);
    }
    // GET /runs/:id/storyboard
    if (url.includes("/storyboard")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            run_id: run?.id ?? 0,
            paragraphs: [
              {
                section_id: "sec-0",
                order: 0,
                text: "A calm morning in Tokyo.",
                display_text: null,
                image_prompt: "panoramic tokyo",
                image_url: null,
                audio_url: "data/artifacts/10/audio/sec-0.wav",
                audio_duration: 5.2,
                subtitles_url: "data/artifacts/10/subtitles/sec-0.srt",
                subtitle_entries: [{ index: 1, start: "00:00:00,000", end: "00:00:05,200", text: "A calm morning in Tokyo." }],
                status: "ready",
                stale_flags: null,
                scene_id: "scene-0",
                image_asset_id: null,
                audio_artifact_id: 2,
                subtitle_artifact_id: 3,
              },
            ],
            render_ready: true,
            total_paragraphs: 1,
            ready_paragraphs: 1,
          }),
      } as Response);
    }
    // GET /runs/:id/visual-assets
    if (url.includes("/visual-assets")) {
      if (!opts.assets) return Promise.resolve({ ok: true, json: () => Promise.resolve({ run_id: run?.id ?? 0, scenes: {}, total_scenes: 0, total_assets: 0 }) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ run_id: run?.id ?? 0, scenes: opts.assets, total_scenes: Object.keys(opts.assets).length, total_assets: Object.values(opts.assets).flat().length }) } as Response);
    }
    // GET /runs/:id/visual-plan
    if (url.includes("/visual-plan")) {
      if (!opts.scenes) return Promise.resolve({ ok: true, json: () => Promise.resolve({ scenes: [] }) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(opts.scenes) } as Response);
    }
    // GET /runs/:id/script
    if (url.includes("/script")) {
      if (!opts.script) return Promise.resolve({ ok: true, json: () => Promise.resolve({ script: null, structured_script: null }) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(opts.script) } as Response);
    }
    // GET /runs/:id
    if (url.match(/\/runs\/\d+$/)) {
      if (!run) return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({ detail: "Run not found" }) } as Response);
      return Promise.resolve({ ok: true, json: () => Promise.resolve(run) } as Response);
    }

    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) } as Response);
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

// ---- tests ----

describe("ReviewPage", () => {
  it("shows loading state initially", () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW);
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Loading review");
  });

  it("shows error for invalid run ID", () => {
    mockFetchAll(null);
    renderPage("abc");
    expect(screen.getByText("Invalid run ID.")).toBeTruthy();
  });

  it("shows run not found error", async () => {
    mockFetchAll(null);
    renderPage("999");
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Run not found");
    });
  });

  it("renders full review at FINAL_REVIEW with all artifacts", async () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, {
      script: MOCK_SCRIPT,
      scenes: MOCK_SCENES,
      assets: MOCK_ASSETS,
      preview: MOCK_PREVIEW,
    });
    renderPage();

    // Wait for data to load
    await waitFor(() => {
      expect(screen.getByTestId("review-script-section")).toBeTruthy();
    });

    // Script section
    expect(screen.getByText(/calm morning in Tokyo/)).toBeTruthy();

    // Visual plan section
    expect(screen.getByTestId("review-visual-plan-section")).toBeTruthy();
    expect(screen.getAllByText("scene-0").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("scene-1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Tokyo skyline")).toBeTruthy();

    // Visual assets section
    expect(screen.getByTestId("review-assets-section")).toBeTruthy();
    expect(screen.getByText(/scene-0\.png/)).toBeTruthy();

    // Storyboard section (replaces audio + subtitle sections)
    expect(screen.getByTestId("review-storyboard-section")).toBeTruthy();
    // Video section — video is now rendered as <video> element, no path text
    expect(screen.getByTestId("review-video-section")).toBeTruthy();
    const videoEl = screen.getByTestId("review-video-section").querySelector("video");
    expect(videoEl).toBeTruthy();
    expect(videoEl?.getAttribute("src")).toContain("output.mp4");
    expect(screen.getByText("shorts_default")).toBeTruthy();
  });

  it("shows empty state at IDEA_READY", async () => {
    mockFetchAll(MOCK_RUN_IDEA_READY);
    renderPage("11");

    await waitFor(() => {
      expect(screen.getByTestId("review-empty")).toBeTruthy();
    });
    expect(screen.getByText("No outputs yet")).toBeTruthy();
    expect(screen.getByText(/Go to editor/)).toBeTruthy();
  });

  it("shows edit links pointing to project page", async () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, {
      script: MOCK_SCRIPT,
      scenes: MOCK_SCENES,
      assets: MOCK_ASSETS,
      preview: MOCK_PREVIEW,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("review-script-section")).toBeTruthy();
    });

    // Multiple "Edit in Project" links
    const editLinks = screen.getAllByText(/Edit in Project/);
    expect(editLinks.length).toBeGreaterThanOrEqual(1);
    // All should link to /projects/5
    editLinks.forEach((link) => {
      expect(link.closest("a")?.getAttribute("href")).toBe("/projects/5");
    });
  });

  it("renders Back to Editor button", async () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, { script: MOCK_SCRIPT });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("review-script-section")).toBeTruthy();
    });

    const backBtn = screen.getByText("Back to Editor");
    expect(backBtn).toBeTruthy();
    expect(backBtn.closest("a")?.getAttribute("href")).toBe("/projects/5");
  });

  it("displays pipeline stepper with current stage", async () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, { script: MOCK_SCRIPT });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/FINAL_REVIEW/)).toBeTruthy();
    });
  });

  it("shows storyboard section when preview has audio data", async () => {
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, { preview: MOCK_PREVIEW });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("review-storyboard-section")).toBeTruthy();
    });
  });

  it("handles wrapped visual-assets response with scenes field (regression)", async () => {
    // The /visual-assets endpoint returns { run_id, scenes, total_scenes, total_assets }
    // NOT a raw Record<string, Asset[]>. Verify ReviewPage correctly extracts .scenes.
    mockFetchAll(MOCK_RUN_FINAL_REVIEW, {
      script: MOCK_SCRIPT,
      scenes: MOCK_SCENES,
      assets: MOCK_ASSETS,
      preview: MOCK_PREVIEW,
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("review-assets-section")).toBeTruthy();
    });

    // Assets from wrapped response should render correctly
    expect(screen.getByText(/scene-0\.png/)).toBeTruthy();
    expect(screen.getByText(/scene-1\.png/)).toBeTruthy();
  });
});
