import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import ModelSelector from "../components/creator/ModelSelector";

const MOCK_RESPONSE = {
  script_models: [
    { key: "qwen3-4b", label: "Qwen3 4B (Local)", provider_type: "ollama", is_local: true, requires_gpu: true, status: "available" as const },
    { key: "gpt-4o-mini", label: "GPT-4o Mini (Remote)", provider_type: "openai", is_local: false, requires_gpu: false, status: "unavailable" as const },
  ],
  image_models: [
    { key: "sd15", label: "Stable Diffusion 1.5 (Local)", provider_type: "stable-diffusion", is_local: true, requires_gpu: true, status: "available" as const },
  ],
  tts_models: [
    { key: "qwen-tts", label: "Qwen TTS (Local)", provider_type: "qwen-tts", is_local: true, requires_gpu: true, status: "unknown" as const },
  ],
  stt_models: [],
};

function mockFetchSuccess() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(MOCK_RESPONSE),
  } as Response);
}

function mockFetchError() {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status: 500,
    json: () => Promise.resolve({}),
  } as Response);
}

describe("ModelSelector", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders loading state initially", () => {
    // Never resolve fetch
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    render(<ModelSelector />);
    expect(screen.getByTestId("model-selector-loading")).toBeTruthy();
  });

  it("renders model lists after fetch", async () => {
    mockFetchSuccess();
    render(<ModelSelector />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    expect(screen.getByText("Qwen3 4B (Local)")).toBeTruthy();
    expect(screen.getByText("GPT-4o Mini (Remote)")).toBeTruthy();
    expect(screen.getByText("Stable Diffusion 1.5 (Local)")).toBeTruthy();
    expect(screen.getByText("Qwen TTS (Local)")).toBeTruthy();
  });

  it("calls onSelectionChange when model clicked", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("GPT-4o Mini (Remote)"));
    expect(onChange).toHaveBeenCalledWith("script", "gpt-4o-mini");
  });

  it("handles fetch error gracefully", async () => {
    mockFetchError();
    render(<ModelSelector />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector-error")).toBeTruthy();
    });

    expect(screen.getByText(/Failed to fetch models: 500/)).toBeTruthy();
  });

  it("default selection mode selects first available model", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // qwen3-4b should be auto-selected (first available in script)
    const qwenItem = screen.getByText("Qwen3 4B (Local)").closest("li");
    expect(qwenItem?.getAttribute("aria-selected")).toBe("true");

    // gpt-4o-mini should NOT be selected
    const gptItem = screen.getByText("GPT-4o Mini (Remote)").closest("li");
    expect(gptItem?.getAttribute("aria-selected")).toBe("false");
  });

  it("respects override mode with selectedModels prop", async () => {
    mockFetchSuccess();
    render(<ModelSelector selectedModels={{ script: "gpt-4o-mini" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // In override mode, gpt-4o-mini should be selected
    const gptItem = screen.getByText("GPT-4o Mini (Remote)").closest("li");
    expect(gptItem?.getAttribute("aria-selected")).toBe("true");

    const qwenItem = screen.getByText("Qwen3 4B (Local)").closest("li");
    expect(qwenItem?.getAttribute("aria-selected")).toBe("false");
  });

  it("shows only specified categories", async () => {
    mockFetchSuccess();
    render(<ModelSelector categories={["script"]} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    expect(screen.getByText("Script Model")).toBeTruthy();
    expect(screen.queryByText("Image Model")).toBeNull();
    expect(screen.queryByText("TTS Model")).toBeNull();
  });

  it("shows status badges for each model", async () => {
    mockFetchSuccess();
    render(<ModelSelector />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Check status badges exist
    const availableBadges = screen.getAllByText("available");
    expect(availableBadges.length).toBe(2); // qwen3-4b + sd15

    expect(screen.getByText("unavailable")).toBeTruthy();
    expect(screen.getByText("unknown")).toBeTruthy();
  });
});
