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

function mockFetchSuccess() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(MOCK_MODELS),
  } as Response);
}

function renderCreatePage() {
  return render(
    <MemoryRouter>
      <CreatePage />
    </MemoryRouter>,
  );
}

describe("CreatePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockFetchSuccess();
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

  it("submit logs form state to console", () => {
    const consoleSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    renderCreatePage();

    fireEvent.click(screen.getByRole("button", { name: "Create Project" }));
    expect(consoleSpy).toHaveBeenCalledWith(
      "CreatePage submit (stub):",
      expect.objectContaining({ tab: "idea" }),
    );
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
});
