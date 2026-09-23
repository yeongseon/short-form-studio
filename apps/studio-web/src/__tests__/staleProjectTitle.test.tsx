import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import ProjectPage from "../pages/ProjectPage";
import { deferred, json } from "./visualPlanFixtures";

afterEach(() => { vi.unstubAllGlobals(); });

it("shows project B title after navigating from an edited project A", async () => {
  // Given a mounted project editor with a draft for A.
  vi.stubGlobal("fetch", vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/projects/1")) return json({ id: 1, title: "A title", source_type: "idea", status: "active" });
    if (url.endsWith("/projects/2")) return json({ id: 2, title: "B title", source_type: "idea", status: "active" });
    return json({ runs: [], total: 0 });
  }));
  function Navigation() {
    const navigate = useNavigate();
    return <button type="button" onClick={() => navigate("/projects/2")}>Open B</button>;
  }
  render(<MemoryRouter initialEntries={["/projects/1"]}>
    <Navigation />
    <Routes><Route path="/projects/:projectId" element={<ProjectPage />} /></Routes>
  </MemoryRouter>);
  await waitFor(() => expect(screen.getByTestId("project-title")).toHaveValue("A title"));
  fireEvent.change(screen.getByTestId("project-title"), { target: { value: "A local draft" } });
  // When navigating to B in the same mounted page.
  fireEvent.click(screen.getByRole("button", { name: "Open B" }));
  // Then B is displayed without A's title draft.
  await waitFor(() => expect(screen.getByTestId("project-title")).toHaveValue("B title"));
});

it("ignores a completed A title save after navigating to B", async () => {
  // Given a title save started for A but still pending on the server.
  const oldSave = deferred<Response>();
  const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PATCH") return oldSave.promise;
    if (url.endsWith("/projects/1")) return json({ id: 1, title: "A title", source_type: "idea", status: "active" });
    if (url.endsWith("/projects/2")) return json({ id: 2, title: "B title", source_type: "idea", status: "active" });
    return json({ runs: [], total: 0 });
  });
  vi.stubGlobal("fetch", fetchMock);
  function Navigation() {
    const navigate = useNavigate();
    return <button type="button" onClick={() => navigate("/projects/2")}>Open B</button>;
  }
  render(<MemoryRouter initialEntries={["/projects/1"]}>
    <Navigation />
    <Routes><Route path="/projects/:projectId" element={<ProjectPage />} /></Routes>
  </MemoryRouter>);
  await waitFor(() => expect(screen.getByTestId("project-title")).toHaveValue("A title"));
  fireEvent.change(screen.getByTestId("project-title"), { target: { value: "A saved later" } });
  fireEvent.blur(screen.getByTestId("project-title"));
  fireEvent.click(screen.getByRole("button", { name: "Open B" }));
  await waitFor(() => expect(screen.getByTestId("project-title")).toHaveValue("B title"));
  // When A's save resolves after B is mounted.
  await act(async () => { oldSave.resolve(json({ title: "A saved later" })); });
  // Then B's title and project identity remain unchanged.
  expect(screen.getByTestId("project-title")).toHaveValue("B title");
  fireEvent.blur(screen.getByTestId("project-title"));
  expect(fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/projects/2") && init?.method === "PATCH")).toHaveLength(0);
});
