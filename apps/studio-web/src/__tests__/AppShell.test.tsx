import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect } from "vitest";

import AppShell from "../components/layout/AppShell";

function renderWithRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/create" element={<div>CreatePage</div>} />
          <Route path="/runs" element={<div>RunsPage</div>} />
          <Route path="/projects/:id" element={<div>ProjectPage</div>} />
          <Route path="/review/:id" element={<div>ReviewPage</div>} />
          <Route path="/ops" element={<div>OpsPage</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("renders navigation bar", () => {
    renderWithRoute("/create");
    expect(screen.getByTestId("app-nav")).toBeInTheDocument();
  });

  it("renders brand link", () => {
    renderWithRoute("/create");
    expect(screen.getByText("Short-Form Pipeline")).toBeInTheDocument();
  });

  it("renders creator nav section", () => {
    renderWithRoute("/create");
    expect(screen.getByTestId("creator-nav")).toBeInTheDocument();
    expect(screen.getByText("Create")).toBeInTheDocument();
    expect(screen.getByText("Projects")).toBeInTheDocument();
  });

  it("renders ops nav section", () => {
    renderWithRoute("/create");
    expect(screen.getByTestId("ops-nav")).toBeInTheDocument();
    expect(screen.getByText("Ops")).toBeInTheDocument();
  });

  it("renders child route content via Outlet", () => {
    renderWithRoute("/create");
    expect(screen.getByText("CreatePage")).toBeInTheDocument();
  });

  it("renders ProjectPage for /projects/:id route", () => {
    renderWithRoute("/projects/5");
    expect(screen.getByText("ProjectPage")).toBeInTheDocument();
  });

  it("renders OpsPage for /ops route", () => {
    renderWithRoute("/ops");
    expect(screen.getByText("OpsPage")).toBeInTheDocument();
  });

  it("highlights Create link when on /create", () => {
    renderWithRoute("/create");
    const createLink = screen.getByText("Create");
    expect(createLink).toHaveStyle({ fontWeight: 600 });
  });

  it("highlights Projects link when on /projects/:id", () => {
    renderWithRoute("/projects/5");
    const projectsLink = screen.getByText("Projects");
    expect(projectsLink).toHaveStyle({ fontWeight: 600 });
  });

  it("highlights Projects link when on /review/:id", () => {
    renderWithRoute("/review/10");
    const projectsLink = screen.getByText("Projects");
    expect(projectsLink).toHaveStyle({ fontWeight: 600 });
  });

  it("highlights Ops link when on /ops", () => {
    renderWithRoute("/ops");
    const opsLink = screen.getByText("Ops");
    expect(opsLink).toHaveStyle({ fontWeight: 600 });
  });
});
