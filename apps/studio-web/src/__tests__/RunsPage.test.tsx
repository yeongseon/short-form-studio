import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import RunsPage from "../pages/RunsPage";

const MOCK_PROJECTS = [
  {
    id: 1,
    title: "Morning Routine",
    source_type: "idea",
    status: "active",
    latest_run: { run_id: 11, current_stage: "SCRIPT_REVIEW", status: "running" },
    created_at: "2025-03-15T10:00:00Z",
    updated_at: "2025-03-15T12:00:00Z",
  },
  {
    id: 2,
    title: "Cooking Tips",
    source_type: "markdown",
    status: "draft",
    latest_run: null,
    created_at: "2025-03-14T08:00:00Z",
    updated_at: "2025-03-14T09:00:00Z",
  },
  {
    id: 3,
    title: null,
    source_type: "url",
    status: "completed",
    latest_run: { run_id: 14, current_stage: "FINAL_REVIEW", status: "completed" },
    created_at: "2025-03-13T06:00:00Z",
    updated_at: "2025-03-13T07:00:00Z",
  },
];

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/runs"]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <RunsPage />
    </MemoryRouter>,
  );
}

function mockFetchOk(projects: typeof MOCK_PROJECTS, total?: number) {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ projects, total: total ?? projects.length }),
  } as Response);
}

function mockFetchError(status = 500, detail = "Internal error") {
  vi.spyOn(globalThis, "fetch").mockResolvedValue({
    ok: false,
    status,
    json: () => Promise.resolve({ detail }),
  } as Response);
}

beforeEach(() => {
  vi.restoreAllMocks();
  mockNavigate.mockReset();
});

describe("RunsPage", () => {
  // --- Loading ---
  it("shows loading state initially", () => {
    // fetch that never resolves
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("status")).toHaveTextContent("Loading projects");
  });

  // --- Empty ---
  it("shows empty state when no projects", async () => {
    mockFetchOk([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
    expect(screen.getByText("No projects yet")).toBeInTheDocument();
  });

  it("empty state has a create project button", async () => {
    mockFetchOk([]);
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
    const btn = screen.getByRole("button", { name: "Create Project" });
    fireEvent.click(btn);
    expect(mockNavigate).toHaveBeenCalledWith("/create");
  });

  // --- Error ---
  it("shows error message on fetch failure", async () => {
    mockFetchError(500, "Internal error");
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Internal error");
  });

  it("retry button re-fetches projects", async () => {
    mockFetchError(500, "Server down");
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });

    // Now fix the mock
    vi.restoreAllMocks();
    mockFetchOk(MOCK_PROJECTS);

    const retryBtn = screen.getByRole("button", { name: "Retry" });
    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
  });

  it("shows generic error when fetch throws", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("Network error"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Network error");
  });

  // --- Data rendering ---
  it("renders project list with titles", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    expect(screen.getByText("Cooking Tips")).toBeInTheDocument();
  });

  it("shows 'Untitled' for null titles", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Untitled")).toBeInTheDocument();
    });
  });

  it("renders source type labels", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Idea")).toBeInTheDocument();
    });
    expect(screen.getByText("Markdown")).toBeInTheDocument();
    expect(screen.getByText("URL")).toBeInTheDocument();
  });

  it("renders status badges", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("running")).toBeInTheDocument();
    });
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("shows latest run stage when available", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("SCRIPT_REVIEW")).toBeInTheDocument();
    });
  });

  it("renders formatted dates", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Mar 15, 2025")).toBeInTheDocument();
    });
  });

  // --- Navigation ---
  it("clicking a row navigates to project page", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    const row = screen.getByText("Morning Routine").closest("tr")!;
    fireEvent.click(row);
    expect(mockNavigate).toHaveBeenCalledWith("/projects/1");
  });

  it("pressing Enter on a row navigates to project page", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Cooking Tips")).toBeInTheDocument();
    });
    const row = screen.getByText("Cooking Tips").closest("tr")!;
    fireEvent.keyDown(row, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/projects/2");
  });

  it("+ New Project button navigates to /create", async () => {
    mockFetchOk(MOCK_PROJECTS);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("+ New Project"));
    expect(mockNavigate).toHaveBeenCalledWith("/create");
  });

  // --- Pagination ---
  it("does not show pagination when total <= PAGE_SIZE", async () => {
    mockFetchOk(MOCK_PROJECTS, 3);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    expect(screen.queryByLabelText("Next page")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Previous page")).not.toBeInTheDocument();
  });

  it("shows pagination when total > PAGE_SIZE", async () => {
    mockFetchOk(MOCK_PROJECTS, 25);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Next page")).toBeInTheDocument();
    expect(screen.getByLabelText("Previous page")).toBeInTheDocument();
    expect(screen.getByText(/Showing 1–20 of 25/)).toBeInTheDocument();
  });

  it("Previous button is disabled on first page", async () => {
    mockFetchOk(MOCK_PROJECTS, 25);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Previous page")).toBeDisabled();
  });

  it("Next button fetches next page", async () => {
    mockFetchOk(MOCK_PROJECTS, 25);
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Morning Routine")).toBeInTheDocument();
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fireEvent.click(screen.getByLabelText("Next page"));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining("offset=20"),
        undefined,
      );
    });
  });

  // --- API call ---
  it("calls fetch with correct URL on mount", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ projects: [], total: 0 }),
    } as Response);

    renderPage();

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith("/api/creator/projects?limit=20&offset=0", undefined);
    });
  });

  // --- Header ---
  it("renders page heading", async () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByRole("heading", { name: "Projects" })).toBeInTheDocument();
  });

  // --- Fallback error when json parse fails ---
  it("shows fallback error when json parse fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.reject(new Error("parse error")),
    } as Response);
    renderPage();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Request failed (502)");
  });
});
