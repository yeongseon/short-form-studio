import { render, screen } from "@testing-library/react";
import { MemoryRouter, Navigate, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";

import AppShell from "../components/layout/AppShell";

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

function renderApp(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
            path="/settings"
            element={<StubPage testId="page-settings" />}
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

  it("renders OpsPage at /ops", () => {
    renderApp("/ops");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-ops")).toBeInTheDocument();
  });

  it("renders SettingsPage at /settings", () => {
    renderApp("/settings");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
    expect(screen.getByTestId("page-settings")).toBeInTheDocument();
  });

  it("redirects / to /create", () => {
    renderApp("/");
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
  });

  it("redirects unknown route to /create", () => {
    renderApp("/nonexistent");
    expect(screen.getByTestId("page-create")).toBeInTheDocument();
  });

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
