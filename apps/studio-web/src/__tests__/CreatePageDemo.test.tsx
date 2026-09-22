import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import CreatePage from "../pages/CreatePage";

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

const MOCK_MODELS = {
  script_models: [],
  image_models: [],
  tts_models: [],
  stt_models: [],
};

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return { ok, status, json: () => Promise.resolve(body) } as Response;
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockNavigate.mockClear();
});

describe("CreatePage demo Short touchpoint (P0-4)", () => {
  it("seeds a demo run and navigates to the seeded project", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) return Promise.resolve(jsonResponse(MOCK_MODELS));
      if (url.endsWith("/workspaces")) return Promise.resolve(jsonResponse({ workspaces: [{ id: 7 }] }));
      if (url.includes("/demo-short/runs")) {
        return Promise.resolve(
          jsonResponse({ run: { project_id: 202 }, seeded_project_id: 202, timeline_id: "demo-timeline", plan: {} }),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });

    render(
      <MemoryRouter>
        <CreatePage />
      </MemoryRouter>,
    );

    const button = screen.getByTestId("try-demo-button");
    fireEvent.click(button);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/projects/202");
    });
  });

  it("shows the structured error and does not navigate when the demo fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.includes("/models")) return Promise.resolve(jsonResponse(MOCK_MODELS));
      if (url.endsWith("/workspaces")) return Promise.resolve(jsonResponse({ workspaces: [{ id: 7 }] }));
      if (url.includes("/demo-short/runs")) {
        return Promise.resolve(
          jsonResponse(
            {
              detail: "demo prerequisites not configured",
              error: { code: "VALIDATION", category: "VALIDATION", retryable: false, recovery_steps: ["Set OPENAI_API_KEY"] },
            },
            false,
            409,
          ),
        );
      }
      return Promise.resolve(jsonResponse({}));
    });

    render(
      <MemoryRouter>
        <CreatePage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("try-demo-button"));

    await waitFor(() => {
      expect(screen.getByTestId("demo-error")).toBeInTheDocument();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
