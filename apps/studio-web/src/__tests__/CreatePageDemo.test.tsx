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

const PLAN = {
  ready: true, blocking_reasons: [], required_approvals: ["timeline_render"],
  cost_line_items: [], estimated_total_cost_usd: 0,
  external_exposure: "local_only", next_action: "Review the saved timeline before rendering",
};

function discovery(url: string): Response | undefined {
  if (url.endsWith("/demo-short/plan")) return jsonResponse(PLAN);
  if (url.endsWith("/onboarding")) return jsonResponse({ steps: ["Review your timeline"], review_gates: ["timeline_render"], next_action: "Preview the sample" });
  if (url.endsWith("/provider-config")) return jsonResponse({ providers: [{ provider: "local", label: "Local renderer", hint: "Rendering is local; generation needs a configured provider", status: "available" }] });
  return undefined;
}

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
      const info = discovery(url);
      if (info) return Promise.resolve(info);
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

    fireEvent.click(await screen.findByRole("button", { name: "Create demo Short" }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/projects/202");
    });
  });

  it("shows the structured error and does not navigate when the demo fails", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      const info = discovery(url);
      if (info) return Promise.resolve(info);
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
    fireEvent.click(await screen.findByRole("button", { name: "Create demo Short" }));

    await waitFor(() => {
      expect(screen.getByTestId("demo-error")).toBeInTheDocument();
    });
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("discloses workspace plan and provider hints before creating once", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const info = discovery(url);
      if (info) return info;
      if (url.includes("/models")) return jsonResponse(MOCK_MODELS);
      if (url.endsWith("/workspaces")) return jsonResponse({ workspaces: [{ id: 19 }] });
      if (url.endsWith("/demo-short/runs")) return jsonResponse({ seeded_project_id: 202, run: { id: 8 }, timeline_id: "tl", plan: PLAN });
      return jsonResponse({});
    });
    render(<MemoryRouter><CreatePage /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("try-demo-button"));
    const create = await screen.findByRole("button", { name: "Create demo Short" });
    expect(screen.getByTestId("demo-plan")).toHaveTextContent("$0.00");
    expect(screen.getByTestId("demo-plan")).toHaveTextContent("local_only");
    expect(screen.getByText("Rendering is local; generation needs a configured provider")).toBeInTheDocument();
    expect(spy.mock.calls.some(([url]) => String(url).endsWith("/workspaces/19/demo-short/plan"))).toBe(true);
    expect(spy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    fireEvent.click(create);
    fireEvent.click(create);
    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/projects/202"));
    expect(spy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(spy.mock.calls.some(([url]) => String(url).endsWith("/workspaces/19/demo-short/runs"))).toBe(true);
  });

  it("renders the actual nested 409 and restores the create action", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      const info = discovery(url);
      if (info) return info;
      if (url.includes("/models")) return jsonResponse(MOCK_MODELS);
      if (url.endsWith("/workspaces")) return jsonResponse({ workspaces: [{ id: 7 }] });
      return new Response(JSON.stringify({ detail: { error: "demo prerequisites not configured", plan: { ready: false } } }), { status: 409 });
    });
    render(<MemoryRouter><CreatePage /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("try-demo-button"));
    fireEvent.click(await screen.findByRole("button", { name: "Create demo Short" }));
    expect(await screen.findByTestId("demo-error")).toHaveTextContent("demo prerequisites not configured");
    expect(screen.getByRole("button", { name: "Create demo Short" })).toBeEnabled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("blocks creation when plan prerequisites are missing", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/demo-short/plan")) return jsonResponse({ ...PLAN, ready: false, blocking_reasons: ["Worker unavailable"] });
      const info = discovery(url);
      if (info) return info;
      if (url.includes("/models")) return jsonResponse(MOCK_MODELS);
      return jsonResponse({ workspaces: [{ id: 7 }] });
    });
    render(<MemoryRouter><CreatePage /></MemoryRouter>);
    fireEvent.click(screen.getByTestId("try-demo-button"));
    expect(await screen.findByText("Worker unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create demo Short" })).toBeDisabled();
    expect(spy.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});
