import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CreatePage from "../pages/CreatePage";

const MOCK_MODELS = {
  script_models: [
    { key: "qwen3-4b", label: "Qwen3 4B", provider_type: "ollama", is_local: true, requires_gpu: true, status: "available" as const },
  ],
  image_models: [
    { key: "sd15", label: "SD 1.5", provider_type: "sd", is_local: true, requires_gpu: true, status: "available" as const },
  ],
  tts_models: [],
  stt_models: [],
};

const MOCK_PROJECT = { id: 42, title: "Test", source_type: "idea", idea_brief: "Brief" };
const MOCK_RUN = { id: 7, project_id: 42, current_stage: "IDEA_READY" };

// Track navigate calls
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function mockFetchSuccess() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(MOCK_MODELS),
  } as Response);
}

/** Mock fetch that handles models, project creation, and run creation */
function mockFetchFullFlow() {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = typeof input === "string" ? input : (input as Request).url;

    if (url.includes("/models")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
    }
    if (url.includes("/projects") && url.includes("/runs")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_RUN) } as Response);
    }
    if (url.includes("/projects")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
  });
}

function renderCreatePage() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <CreatePage />
    </MemoryRouter>,
  );
}

describe("CreatePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchSuccess();
    mockNavigate.mockReset();
  });

  it("renders the page heading", () => {
    renderCreatePage();
    expect(screen.getByText("Create New Project")).toBeTruthy();
  });

  it("has 'Start from Idea' tab selected by default", () => {
    renderCreatePage();
    const ideaTab = screen.getByRole("tab", { name: "Start from Idea" });
    expect(ideaTab).toHaveAttribute("aria-selected", "true");

    const mdTab = screen.getByRole("tab", { name: "Start from Markdown" });
    expect(mdTab).toHaveAttribute("aria-selected", "false");
  });

  it("shows idea form fields on the default tab", () => {
    renderCreatePage();
    expect(screen.getByLabelText(/Title/)).toBeTruthy();
    expect(screen.getByLabelText(/Idea Brief/)).toBeTruthy();
    expect(screen.getByLabelText(/Target Duration/)).toBeTruthy();
    expect(screen.getByLabelText(/Content Goal/)).toBeTruthy();
  });

  it("switches to markdown tab when clicked", () => {
    renderCreatePage();
    const mdTab = screen.getByRole("tab", { name: "Start from Markdown" });
    fireEvent.click(mdTab);

    expect(mdTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Start from Idea" })).toHaveAttribute("aria-selected", "false");

    // Markdown tab content should be visible
    expect(screen.getByLabelText(/Markdown Content/)).toBeTruthy();
    expect(screen.getByLabelText(/Or upload a file/)).toBeTruthy();
  });

  it("allows typing in idea form fields", () => {
    renderCreatePage();

    const titleInput = screen.getByLabelText(/^Title/) as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: "My Video" } });
    expect(titleInput.value).toBe("My Video");

    const briefInput = screen.getByLabelText(/Idea Brief/) as HTMLTextAreaElement;
    fireEvent.change(briefInput, { target: { value: "A cooking tutorial" } });
    expect(briefInput.value).toBe("A cooking tutorial");

    const durationInput = screen.getByLabelText(/Target Duration/) as HTMLInputElement;
    fireEvent.change(durationInput, { target: { value: "90" } });
    expect(durationInput.value).toBe("90");

    const goalInput = screen.getByLabelText(/Content Goal/) as HTMLInputElement;
    fireEvent.change(goalInput, { target: { value: "educational" } });
    expect(goalInput.value).toBe("educational");
  });

  it("allows typing in markdown form fields", () => {
    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    const titleInput = screen.getByLabelText(/^Title/) as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: "MD Project" } });
    expect(titleInput.value).toBe("MD Project");

    const mdTextarea = screen.getByLabelText(/Markdown Content/) as HTMLTextAreaElement;
    fireEvent.change(mdTextarea, { target: { value: "# Scene 1\nHello" } });
    expect(mdTextarea.value).toBe("# Scene 1\nHello");
  });

  it("style preset select works", () => {
    renderCreatePage();
    const select = screen.getByLabelText(/Style Preset/) as HTMLSelectElement;
    expect(select.value).toBe("default");

    fireEvent.change(select, { target: { value: "cinematic" } });
    expect(select.value).toBe("cinematic");
  });

  it("render profile select works", () => {
    renderCreatePage();
    const select = screen.getByLabelText(/Render Profile/) as HTMLSelectElement;
    expect(select.value).toBe("shorts_default");

    fireEvent.change(select, { target: { value: "high_quality" } });
    expect(select.value).toBe("high_quality");
  });

  it("has submit button", () => {
    renderCreatePage();
    expect(screen.getByRole("button", { name: "Create Project" })).toBeTruthy();
  });

  it("submit button is present on both tabs", () => {
    renderCreatePage();
    // Idea tab
    expect(screen.getByRole("button", { name: "Create Project" })).toBeTruthy();

    // Markdown tab
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));
    expect(screen.getByRole("button", { name: "Create Project" })).toBeTruthy();
  });

  it("renders ModelSelector with script and image categories", async () => {
    renderCreatePage();

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Should show Script Model and Image Model
    expect(screen.getByText("Script Model")).toBeTruthy();
    expect(screen.getByText("Image Model")).toBeTruthy();
    // Should NOT show TTS or STT
    expect(screen.queryByText("TTS Model")).toBeNull();
    expect(screen.queryByText("STT Model")).toBeNull();
  });

  it("shows only image model on markdown tab", async () => {
    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));
    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });
    expect(screen.getByText("Image Model")).toBeTruthy();
    expect(screen.queryByText("Script Model")).toBeNull();
  });

  it("has proper tablist and tabpanel roles", () => {
    renderCreatePage();
    expect(screen.getByRole("tablist")).toBeTruthy();
    expect(screen.getByRole("tabpanel")).toBeTruthy();
  });

  it("markdown file upload input is present on markdown tab", () => {
    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));
    const fileInput = screen.getByLabelText(/Or upload a file/) as HTMLInputElement;
    expect(fileInput).toBeTruthy();
    expect(fileInput.type).toBe("file");
    expect(fileInput.accept).toBe(".md,.txt");
  });

  it("file upload populates markdown textarea", async () => {
    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    const fileInput = screen.getByLabelText(/Or upload a file/) as HTMLInputElement;
    const fileContent = "# Test Script\nScene one content";
    const file = new File([fileContent], "script.md", { type: "text/markdown" });

    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      const textarea = screen.getByLabelText(/Markdown Content/) as HTMLTextAreaElement;
      expect(textarea.value).toBe(fileContent);
    });
  });

  it("target duration defaults to 60", () => {
    renderCreatePage();
    const durationInput = screen.getByLabelText(/Target Duration/) as HTMLInputElement;
    expect(durationInput.value).toBe("60");
  });

  it("has all style preset options", () => {
    renderCreatePage();
    const select = screen.getByLabelText(/Style Preset/) as HTMLSelectElement;
    const options = Array.from(select.options).map((o) => o.value);
    expect(options).toEqual(["default", "cinematic", "dynamic", "minimal"]);
  });

  // --- New tests for Issue #33: API submission flow ---

  it("submits idea form and navigates to project page", async () => {
    mockFetchFullFlow();
    renderCreatePage();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "My Video" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "A cooking tutorial" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/projects/42");
    });

    // Verify project creation API was called
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const projectCall = calls.find(
      (c: unknown[]) => typeof c[0] === "string" && c[0].includes("/projects") && !c[0].includes("/runs") && !c[0].includes("/models"),
    );
    expect(projectCall).toBeTruthy();
    const projectBody = JSON.parse((projectCall![1] as RequestInit).body as string);
    expect(projectBody.title).toBe("My Video");
    expect(projectBody.source_type).toBe("idea");
    expect(projectBody.idea_brief).toBe("A cooking tutorial");
  });

  it("creates a run with model defaults and metadata", async () => {
    mockFetchFullFlow();
    renderCreatePage();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "My Video" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "Brief" } });
    fireEvent.change(screen.getByLabelText(/Content Goal/), { target: { value: "educational" } });
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "90" } });
    fireEvent.change(screen.getByLabelText(/Render Profile/), { target: { value: "high_quality" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/projects/42");
    });

    // Verify run creation API was called with metadata
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const runCall = calls.find((c: unknown[]) => typeof c[0] === "string" && c[0].includes("/runs"));
    expect(runCall).toBeTruthy();
    const runBody = JSON.parse((runCall![1] as RequestInit).body as string);
    expect(runBody.metadata.content_goal).toBe("educational");
    expect(runBody.metadata.target_duration).toBe(90);
    expect(runBody.style_preset).toBe("default");
    expect(runBody.model_defaults.render_profile).toBe("high_quality");
  });

  it("shows error when project creation fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      // Project creation fails
      return Promise.resolve({
        ok: false,
        status: 400,
        json: () => Promise.resolve({ detail: "Title is required" }),
      } as Response);
    });

    renderCreatePage();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "T" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByTestId("idea-form-error")).toBeTruthy();
    });
    expect(screen.getByTestId("idea-form-error").textContent).toBe("Title is required");
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("shows error when run creation fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      if (url.includes("/projects") && !url.includes("/runs")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
      }
      // Run creation fails
      return Promise.resolve({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ detail: "Internal error" }),
      } as Response);
    });

    renderCreatePage();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "T" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByTestId("idea-form-error")).toBeTruthy();
    });
    expect(screen.getByTestId("idea-form-error").textContent).toBe("Internal error");
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("shows 'Creating…' on submit button while submitting", async () => {
    // Make fetch hang so we can observe the loading state
    let resolveProject!: (value: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      return new Promise((resolve) => { resolveProject = resolve; });
    });

    renderCreatePage();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "T" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Creating…" })).toBeTruthy();
    });

    // Resolve to clean up
    resolveProject({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
  });

  it("renders IdeaForm inside the idea tab panel", () => {
    renderCreatePage();
    const panel = screen.getByRole("tabpanel");
    const form = screen.getByTestId("idea-form");
    expect(panel.contains(form)).toBe(true);
  });

  // --- Markdown submission flow tests ---

  it("submits markdown form and navigates to project page", async () => {
    const MOCK_IMPORT = { project_id: 42, run_id: 7, draft: {} };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      if (url.includes("/import-markdown")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_IMPORT) } as Response);
      }
      if (url.includes("/projects")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });

    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "MD Project" } });
    fireEvent.change(screen.getByLabelText(/Markdown Content/), { target: { value: "# Scene 1\nHello world" } });

    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/projects/42");
    });

    // Verify project creation was called with source_type=markdown
    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const projectCall = calls.find(
      (c: unknown[]) => typeof c[0] === "string" && c[0].includes("/projects") && !c[0].includes("/script") && !c[0].includes("/models"),
    );
    expect(projectCall).toBeTruthy();
    const projectBody = JSON.parse((projectCall![1] as RequestInit).body as string);
    expect(projectBody.source_type).toBe("markdown");
    expect(projectBody.markdown_source).toBe("# Scene 1\nHello world");

    // Verify import-markdown was called
    const importCall = calls.find(
      (c: unknown[]) => typeof c[0] === "string" && c[0].includes("/import-markdown"),
    );
    expect(importCall).toBeTruthy();
    const importBody = JSON.parse((importCall![1] as RequestInit).body as string);
    expect(importBody.markdown).toBe("# Scene 1\nHello world");
  });

  it("does not submit markdown when content is empty", async () => {
    mockFetchFullFlow();
    renderCreatePage();
    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    // Leave markdown content empty, just set title
    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "My Project" } });
    // Clear pre-filled template to test empty submission
    fireEvent.change(screen.getByLabelText(/Markdown Content/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mockNavigate).not.toHaveBeenCalled();
    });
  });

  it("shows error when import-markdown fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      if (url.includes("/import-markdown")) {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: () => Promise.resolve({ detail: "markdown content must not be empty" }),
        } as Response);
      }
      if (url.includes("/projects")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });

    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    fireEvent.change(screen.getByLabelText(/Markdown Content/), { target: { value: "# Test" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(screen.getByTestId("markdown-form-error")).toBeTruthy();
    });
    expect(screen.getByTestId("markdown-form-error").textContent).toBe("markdown content must not be empty");
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("uses 'Untitled' when markdown title is empty", async () => {
    const MOCK_IMPORT = { project_id: 42, run_id: 7, draft: {} };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_MODELS) } as Response);
      }
      if (url.includes("/import-markdown")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_IMPORT) } as Response);
      }
      if (url.includes("/projects")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROJECT) } as Response);
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) } as Response);
    });

    renderCreatePage();
    fireEvent.click(screen.getByRole("tab", { name: "Start from Markdown" }));

    // No title, just markdown content
    fireEvent.change(screen.getByLabelText(/Markdown Content/), { target: { value: "# Scene" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalled();
    });

    const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
    const projectCall = calls.find(
      (c: unknown[]) => typeof c[0] === "string" && c[0].includes("/projects") && !c[0].includes("/script") && !c[0].includes("/models"),
    );
    const projectBody = JSON.parse((projectCall![1] as RequestInit).body as string);
    expect(projectBody.title).toBe("Untitled");
  });
});
