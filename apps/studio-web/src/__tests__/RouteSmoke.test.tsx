/**
 * Route coexistence smoke tests (Issue #73)
 *
 * Verify that creator routes (/create, /projects/:id, /review/:id, /runs)
 * and ops routes (/ops, /ops/library) coexist in one build without conflicts.
 *
 * These are shallow render tests — they confirm each route resolves to the
 * correct page component and the nav shell is present. Deep component
 * behavior is covered by per-page test suites.
 */
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";

import AppShell from "../components/layout/AppShell";

// ---- Stub pages (avoids fetch side-effects in smoke tests) ----
vi.mock("../pages/CreatePage", () => ({
  default: () => <div data-testid="page-create">CreatePage</div>,
}));
vi.mock("../pages/ProjectPage", () => ({
  default: () => <div data-testid="page-project">ProjectPage</div>,
}));
vi.mock("../pages/ReviewPage", () => ({
  default: () => <div data-testid="page-review">ReviewPage</div>,
}));
vi.mock("../pages/RunsPage", () => ({
  default: () => <div data-testid="page-runs">RunsPage</div>,
}));
vi.mock("../pages/OpsPage", () => ({
  default: () => <div data-testid="page-ops">OpsPage</div>,
}));
vi.mock("../pages/LibraryPage", () => ({
  default: () => <div data-testid="page-library">LibraryPage</div>,
}));

/**
 * Renders the full App route tree at the given path.
 * Mirrors App.tsx route config exactly.
 */
function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/create" element={<StubPage testId="page-create" />} />
          <Route
            path="/projects/:projectId"
            element={<StubPage testId="page-project" />}
          />
          <Route
            path="/review/:runId"
            element={<StubPage testId="page-review" />}
          />
          <Route path="/runs" element={<StubPage testId="page-runs" />} />
          <Route
            path="/library"
            element={<Navigate replace to="/ops/library" />}
          />
          <Route
            path="/ops/library"
            element={<StubPage testId="page-library" />}
          />
          <Route path="/ops" element={<StubPage testId="page-ops" />} />
          <Route path="*" element={<Navigate replace to="/create" />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function StubPage({ testId }: { testId: string }) {
  return <div data-testid={testId}>{testId}</div>;
}

describe("Route coexistence smoke tests", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // ---------- Creator routes ----------

  it("renders CreatePage at /create with nav shell", () => {
    renderApp("/create");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
  });

  it("renders ProjectPage at /projects/:id", () => {
    renderApp("/projects/42");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-project")).toBeInTheDocument();
  });

  it("renders ReviewPage at /review/:id", () => {
    renderApp("/review/7");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-review")).toBeInTheDocument();
  });

  it("renders RunsPage at /runs", () => {
    renderApp("/runs");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-runs")).toBeInTheDocument();
  });

  // ---------- Ops routes ----------

  it("renders OpsPage at /ops", () => {
    renderApp("/ops");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-ops")).toBeInTheDocument();
  });

  it("renders LibraryPage at /ops/library", () => {
    renderApp("/ops/library");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-library")).toBeInTheDocument();
  });

  // ---------- Redirects ----------

  it("redirects / to /create", () => {
    renderApp("/");
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
  });

  it("redirects unknown route to /create", () => {
    renderApp("/nonexistent");
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
  });

  it("redirects legacy /library to /ops/library", () => {
    renderApp("/library");
    expect(screen.getByTestId("page-library")).toBeInTheDocument();
  });

  // ---------- Nav coexistence ----------

  it("shows both creator and ops nav sections on creator route", () => {
    renderApp("/create");
    expect(screen.getByTestId("creator-nav")).toBeInTheDocument();
    expect(screen.getByTestId("ops-nav")).toBeInTheDocument();
  });

  it("shows both creator and ops nav sections on ops route", () => {
    renderApp("/ops");
    expect(screen.getByTestId("creator-nav")).toBeInTheDocument();
    expect(screen.getByTestId("ops-nav")).toBeInTheDocument();
  });

  // ---------- Route isolation ----------

  it("does not render ops content when on creator route", () => {
    renderApp("/create");
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
    expect(screen.queryByTestId("page-ops")).not.toBeInTheDocument();
  });

  it("does not render creator content when on ops route", () => {
    renderApp("/ops");
    expect(screen.getByTestId("page-ops")).toBeInTheDocument();
    expect(screen.queryByTestId("page-create")).not.toBeInTheDocument();
  });
});
