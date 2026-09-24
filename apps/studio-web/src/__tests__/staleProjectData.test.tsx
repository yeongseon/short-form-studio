import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useProjectData } from "../pages/project/useProjectData";
import { deferred, json } from "./visualPlanFixtures";

const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>();
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); });

it("keeps the new project when the old project response resolves last", async () => {
  // Given overlapping project requests A and B.
  const oldProject = deferred<Response>();
  fetchMock.mockImplementation((input) => {
    if (String(input).endsWith("/projects/1")) return oldProject.promise;
    if (String(input).endsWith("/projects/2")) return Promise.resolve(json({ id: 2, title: "B", status: "active", source_type: "idea" }));
    return Promise.resolve(json({ runs: [], total: 0 }));
  });
  const hook = renderHook(({ id }) => useProjectData(id), { initialProps: { id: 1 } });
  hook.rerender({ id: 2 });
  await waitFor(() => expect(hook.result.current.project?.title).toBe("B"));
  // When A finishes after B.
  await act(async () => oldProject.resolve(json({ id: 1, title: "A", status: "active", source_type: "idea" })));
  // Then only B remains visible.
  expect(hook.result.current.project?.title).toBe("B");
});

it("ignores a stale poll response after navigating to another project", async () => {
  // Given a polling run A and a pending old poll response.
  const oldPoll = deferred<Response>();
  fetchMock.mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/projects/1")) return Promise.resolve(json({ id: 1, title: "A", source_type: "idea", status: "active" }));
    if (url.endsWith("/projects/2")) return Promise.resolve(json({ id: 2, title: "B", source_type: "idea", status: "active" }));
    if (url.endsWith("/projects/1/runs")) return Promise.resolve(json({ runs: [{ id: 11, project_id: 1, current_stage: "SCRIPT_GENERATING", status: "running", restart_from: null, model_defaults: null }], total: 1 }));
    if (url.endsWith("/projects/2/runs")) return Promise.resolve(json({ runs: [{ id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW", status: "waiting", restart_from: null, model_defaults: null }], total: 1 }));
    return oldPoll.promise;
  });
  const hook = renderHook(({ id }) => useProjectData(id), { initialProps: { id: 1 } });
  await waitFor(() => expect(hook.result.current.run?.id).toBe(11));
  act(() => vi.useFakeTimers());
  await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
  hook.rerender({ id: 2 });
  act(() => vi.useRealTimers());
  await waitFor(() => expect(hook.result.current.run?.id).toBe(22));
  // When the earlier poll finishes last.
  await act(async () => oldPoll.resolve(json({ id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW", status: "waiting", restart_from: null, model_defaults: null })));
  // Then B remains the active run.
  expect(hook.result.current.run?.id).toBe(22);
});

it("does not roll back a newer model choice after an earlier failure", async () => {
  // Given a run and two consecutive choices for the same model.
  const oldSave = deferred<Response>();
  fetchMock.mockImplementation((input, init) => {
    const url = String(input);
    if (init?.method === "PATCH") {
      if (JSON.parse(String(init.body)).image_model === "old") return oldSave.promise;
      return Promise.resolve(json({}));
    }
    if (url.endsWith("/projects/1")) return Promise.resolve(json({ id: 1, title: "A", source_type: "idea", status: "active" }));
    return Promise.resolve(json({ runs: [{ id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW", status: "waiting", restart_from: null, model_defaults: null }], total: 1 }));
  });
  const hook = renderHook(() => useProjectData(1));
  await waitFor(() => expect(hook.result.current.run?.id).toBe(11));
  act(() => hook.result.current.onModelChange("image", "old"));
  act(() => hook.result.current.onModelChange("image", "new"));
  // When the first write fails after the second is accepted.
  await act(async () => oldSave.resolve(json({ detail: "rejected" }, 409)));
  // Then the newer local choice is not rolled back.
  expect(hook.result.current.modelSelection.image_model).toBe("new");
});

it("finishes loading a new project when an old run refresh starts", async () => {
  // Given A is loaded and B's project response is pending.
  const nextProject = deferred<Response>();
  fetchMock.mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/projects/2")) return nextProject.promise;
    if (url.endsWith("/projects/1")) return Promise.resolve(json({ id: 1, title: "A", source_type: "idea", status: "active" }));
    if (url.endsWith("/projects/1/runs")) return Promise.resolve(json({ runs: [{ id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW", status: "waiting", restart_from: null, model_defaults: null }], total: 1 }));
    if (url.endsWith("/projects/2/runs")) return Promise.resolve(json({ runs: [], total: 0 }));
    return Promise.resolve(json({ id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW", status: "waiting", restart_from: null, model_defaults: null }));
  });
  const hook = renderHook(({ id }) => useProjectData(id), { initialProps: { id: 1 } });
  await waitFor(() => expect(hook.result.current.run?.id).toBe(11));
  hook.rerender({ id: 2 });
  // When an old A callback starts while B is loading.
  await act(() => hook.result.current.refreshRun(11));
  await act(async () => { nextProject.resolve(json({ id: 2, title: "B", source_type: "idea", status: "active" })); });
  // Then B's full load can still finish.
  await waitFor(() => expect(hook.result.current.loading).toBe(false));
  expect(hook.result.current.project?.title).toBe("B");
});
