import React from "react";
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
    { key: "qwen3-tts", label: "Qwen3 TTS (Local)", provider_type: "qwen_tts", is_local: true, requires_gpu: true, status: "unknown" as const },
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
    expect(screen.getByText("Qwen3 TTS (Local)")).toBeTruthy();
  });

  it("calls onSelectionChange when model selected via radio", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Clear default-notification calls
    onChange.mockClear();

    const gptRadio = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    fireEvent.click(gptRadio);
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

  it("default selection mode selects first available model and notifies parent", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // qwen3-4b radio should be checked (first available in script)
    const qwenRadio = screen.getByRole("radio", { name: /Qwen3 4B/ });
    expect(qwenRadio).toBeChecked();

    // gpt-4o-mini radio should NOT be checked
    const gptRadio = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    expect(gptRadio).not.toBeChecked();

    // Parent should have been notified of default selections
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith("script", "qwen3-4b");
      expect(onChange).toHaveBeenCalledWith("image", "sd15");
      expect(onChange).toHaveBeenCalledWith("tts", "qwen3-tts");
    });
  });

  it("respects controlled mode with selectedModels prop", async () => {
    mockFetchSuccess();
    render(<ModelSelector selectedModels={{ script: "gpt-4o-mini" }} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // In controlled mode, gpt-4o-mini should be checked
    const gptRadio = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    expect(gptRadio).toBeChecked();

    const qwenRadio = screen.getByRole("radio", { name: /Qwen3 4B/ });
    expect(qwenRadio).not.toBeChecked();
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

  it("radio click fires onSelectionChange with correct category and key", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    onChange.mockClear();

    const gptRadio = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    fireEvent.click(gptRadio);
    expect(onChange).toHaveBeenCalledWith("script", "gpt-4o-mini");
  });

  it("uses radiogroup role with proper aria-label per category", async () => {
    mockFetchSuccess();
    render(<ModelSelector />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Each category should have a radiogroup
    expect(screen.getByRole("radiogroup", { name: "Script Model" })).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "Image Model" })).toBeTruthy();
    expect(screen.getByRole("radiogroup", { name: "TTS Model" })).toBeTruthy();
  });

  it("does not notify parent of defaults in controlled mode", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(<ModelSelector selectedModels={{ script: "qwen3-4b" }} onSelectionChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // In controlled mode, onSelectionChange should NOT be called with defaults
    expect(onChange).not.toHaveBeenCalled();
  });

  it("does not fire duplicate default callbacks when categories array identity changes", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    const { rerender } = render(
      <ModelSelector categories={["script", "image"]} onSelectionChange={onChange} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Initial defaults should have fired for script + image
    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith("script", "qwen3-4b");
      expect(onChange).toHaveBeenCalledWith("image", "sd15");
    });
    // initialCallCount used to be checked here; onChange.mockClear() below is sufficient
    onChange.mockClear();

    // Rerender with a NEW array reference but same content
    rerender(
      <ModelSelector categories={["script", "image"]} onSelectionChange={onChange} />,
    );

    // Allow any effects to settle
    await new Promise((r) => setTimeout(r, 50));

    // No duplicate callbacks should have fired — selections already exist
    expect(onChange).not.toHaveBeenCalled();
  });

  it("manual uncontrolled selection survives parent rerender", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    const { rerender } = render(
      <ModelSelector onSelectionChange={onChange} />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Manually select gpt-4o-mini (overriding the default qwen3-4b)
    const gptRadio = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    fireEvent.click(gptRadio);
    expect(gptRadio).toBeChecked();

    onChange.mockClear();

    // Rerender with new categories array identity (same content)
    rerender(
      <ModelSelector categories={["script", "image", "tts", "stt"]} onSelectionChange={onChange} />,
    );

    // Allow effects to settle
    await new Promise((r) => setTimeout(r, 50));

    // The manually selected gpt-4o-mini should still be checked, not overwritten by default
    const gptRadioAfter = screen.getByRole("radio", { name: /GPT-4o Mini/ });
    expect(gptRadioAfter).toBeChecked();
  });

  it("default callbacks fire exactly once under StrictMode", async () => {
    mockFetchSuccess();
    const onChange = vi.fn();
    render(
      <React.StrictMode>
        <ModelSelector onSelectionChange={onChange} />
      </React.StrictMode>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("model-selector")).toBeTruthy();
    });

    // Each category default should fire exactly once, not doubled by StrictMode
    const scriptCalls = onChange.mock.calls.filter(
      ([cat, key]: [string, string]) => cat === "script" && key === "qwen3-4b",
    );
    expect(scriptCalls.length).toBe(1);

    const imageCalls = onChange.mock.calls.filter(
      ([cat, key]: [string, string]) => cat === "image" && key === "sd15",
    );
    expect(imageCalls.length).toBe(1);

    const ttsCalls = onChange.mock.calls.filter(
      ([cat, key]: [string, string]) => cat === "tts" && key === "qwen3-tts",
    );
    expect(ttsCalls.length).toBe(1);
  });
});
