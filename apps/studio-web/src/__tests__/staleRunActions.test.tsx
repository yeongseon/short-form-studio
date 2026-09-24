import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRunActions } from "../pages/project/useRunActions";
import { deferred, json } from "./visualPlanFixtures";
import type { ProjectDetail, RunDetail } from "../pages/project/types";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("does not publish an old run action result after navigating to another project", async () => {
  // Given an in-flight approval for A, with the same hook later displaying B.
  const oldApproval = deferred<Response>();
  const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(async () => oldApproval.promise);
  vi.stubGlobal("fetch", fetchMock);
  const refreshRun = vi.fn<Parameters<() => Promise<void>>, ReturnType<() => Promise<void>>>().mockResolvedValue(undefined);
  const a = { id: 1, title: "A" } as ProjectDetail;
  const b = { id: 2, title: "B" } as ProjectDetail;
  const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const navigate = vi.fn<Parameters<(path: string) => void>, void>();
  const hook = renderHook(({ project, run, projectId }) => useRunActions({
    run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
  }), { initialProps: { project: a, run: runA, projectId: 1 } });
  let pending: Promise<void> | undefined;
  act(() => { pending = hook.result.current.handleApprove(); });
  hook.rerender({ project: b, run: runB, projectId: 2 });

  // When A's approval finishes after B is active.
  await act(async () => { oldApproval.resolve(json({})); await pending; });

  // Then no A toast or refresh is applied to the B view.
  expect(hook.result.current.toast).toBeNull();
  expect(refreshRun).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(hook.result.current.approving).toBe(false);
});

it.each(["handleGoBack", "handleApproveVisualPlan", "handleRender", "handleStop", "handleResume", "handleApproveFinal"] as const)(
  "ignores %s completion after navigating away",
  async (action) => {
    // Given an in-flight action belonging to A and a mounted B view.
    const previous = deferred<Response>();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => previous.promise);
    vi.stubGlobal("fetch", fetchMock);
    const refreshRun = vi.fn(async () => {});
    const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
    const navigate = vi.fn<[string], void>();
    const a = { id: 1, title: "A" } as ProjectDetail;
    const b = { id: 2, title: "B" } as ProjectDetail;
    const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const hook = renderHook(({ project, run, projectId }) => useRunActions({
      run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
    }), { initialProps: { project: a, run: runA, projectId: 1 } });
    let pending: Promise<void> | undefined;
    act(() => { pending = hook.result.current[action](); });
    hook.rerender({ project: b, run: runB, projectId: 2 });

    // When the old request completes after B is active.
    await act(async () => { previous.resolve(json({})); await pending; });

    // Then the new view receives no stale message or refresh.
    expect(hook.result.current.toast).toBeNull();
    expect(refreshRun).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(hook.result.current[action === "handleGoBack" ? "goingBack" : action === "handleRender" ? "generating" : action === "handleStop" ? "stopping" : action === "handleResume" ? "resuming" : "approving"]).toBe(false);
  },
);

it.each(["handleRestart", "handleRestartVisualPlan"] as const)(
  "does not dispatch follow-up work from stale %s",
  async (action) => {
    // Given the first restart request for A is pending when B opens.
    const previous = deferred<Response>();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => previous.promise);
    vi.stubGlobal("fetch", fetchMock);
    const refreshRun = vi.fn(async () => {});
    const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
    const navigate = vi.fn<[string], void>();
    const a = { id: 1, title: "A" } as ProjectDetail;
    const b = { id: 2, title: "B" } as ProjectDetail;
    const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const hook = renderHook(({ project, run, projectId }) => useRunActions({
      run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
    }), { initialProps: { project: a, run: runA, projectId: 1 } });
    let pending: Promise<void> | undefined;
    act(() => { pending = hook.result.current[action](); });
    hook.rerender({ project: b, run: runB, projectId: 2 });

    // When the earlier restart response arrives.
    await act(async () => { previous.resolve(json({})); await pending; });

    // Then no second request, toast, or refresh is started from A.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(hook.result.current.toast).toBeNull();
    expect(refreshRun).not.toHaveBeenCalled();
    expect(hook.result.current.restarting).toBe(false);
  },
);

it("does not run a pending action completion after unmount", async () => {
  // Given an approval pending when its mounted project page closes.
  const oldApproval = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => oldApproval.promise));
  const refreshRun = vi.fn(async () => {});
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const navigate = vi.fn<[string], void>();
  const hook = renderHook(() => useRunActions({
    run: { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail,
    project: { id: 1, title: "A" } as ProjectDetail,
    numericProjectId: 1, modelSelection: {}, setProject, refreshRun, navigate,
  }));
  let pending: Promise<void> | undefined;
  act(() => { pending = hook.result.current.handleApprove(); });
  hook.unmount();

  // When the old request completes after unmount.
  await act(async () => { oldApproval.resolve(json({})); await pending; });

  // Then it performs no visible completion or refresh.
  expect(refreshRun).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
});

it("cancels a scheduled refresh when the active run changes", async () => {
  // Given a completed generation action with a delayed run refresh.
  vi.stubGlobal("fetch", vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockResolvedValue(json({})));
  const refreshRun = vi.fn(async () => {});
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const navigate = vi.fn<[string], void>();
  const project = { id: 1, title: "A" } as ProjectDetail;
  const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const runB = { id: 12, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const hook = renderHook(({ run }) => useRunActions({
    run, project, numericProjectId: 1, modelSelection: {}, setProject, refreshRun, navigate,
  }), { initialProps: { run: runA } });
  act(() => { vi.useFakeTimers(); });
  await act(async () => { await hook.result.current.handleGenerate(); });

  // When the same project switches to B's run before the refresh timer fires.
  hook.rerender({ run: runB });
  await act(async () => { await vi.runAllTimersAsync(); });

  // Then the obsolete run is not refreshed.
  expect(refreshRun).not.toHaveBeenCalled();
});

it("starts a new action for B rather than reusing A's callback after navigation", async () => {
  // Given the same mounted hook switches from run A to run B.
  const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockResolvedValue(json({}));
  vi.stubGlobal("fetch", fetchMock);
  const refreshRun = vi.fn(async () => {});
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const navigate = vi.fn<[string], void>();
  const a = { id: 1, title: "A" } as ProjectDetail;
  const b = { id: 2, title: "B" } as ProjectDetail;
  const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const hook = renderHook(({ project, run, projectId }) => useRunActions({
    run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
  }), { initialProps: { project: a, run: runA, projectId: 1 } });
  hook.rerender({ project: b, run: runB, projectId: 2 });

  // When the B view approves its run.
  await act(async () => { await hook.result.current.handleApprove(); });

  // Then only B's run receives the action and refresh.
  expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/runs/22/approve-script");
  expect(refreshRun).toHaveBeenCalledWith(22);
});

it.each(["handleApprove", "handleRestart"] as const)(
  "ignores an old %s completion after A to B to A navigation",
  async (action) => {
    // Given an old A request pending across a B visit and return to A.
    const old = deferred<Response>();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => old.promise);
    vi.stubGlobal("fetch", fetchMock);
    const refreshRun = vi.fn(async () => {});
    const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
    const navigate = vi.fn<[string], void>();
    const a = { id: 1, title: "A" } as ProjectDetail;
    const b = { id: 2, title: "B" } as ProjectDetail;
    const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
    const hook = renderHook(({ project, run, projectId }) => useRunActions({
      run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
    }), { initialProps: { project: a, run: runA, projectId: 1 } });
    let pending: Promise<void> | undefined;
    act(() => { pending = hook.result.current[action](); });
    hook.rerender({ project: b, run: runB, projectId: 2 });
    hook.rerender({ project: a, run: runA, projectId: 1 });

    // When the first A response arrives after the second A visit.
    await act(async () => { old.resolve(json({})); await pending; });

    // Then it does not toast, refresh, or dispatch old follow-up work.
    expect(hook.result.current.toast).toBeNull();
    expect(refreshRun).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  },
);

it("ignores an old title save after A to B to A navigation", async () => {
  // Given an A title save that remains pending through a B visit.
  const old = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => old.promise));
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const refreshRun = vi.fn(async () => {});
  const navigate = vi.fn<[string], void>();
  const a = { id: 1, title: "A" } as ProjectDetail;
  const b = { id: 2, title: "B" } as ProjectDetail;
  const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;
  const hook = renderHook(({ project, run, projectId }) => useRunActions({
    run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
  }), { initialProps: { project: a, run: runA, projectId: 1 } });
  act(() => { hook.result.current.setTitleDraft("First A edit"); });
  let pending: Promise<void> | undefined;
  act(() => { pending = hook.result.current.handleTitleSave(); });
  hook.rerender({ project: b, run: runB, projectId: 2 });
  hook.rerender({ project: a, run: runA, projectId: 1 });

  // When the first A save resolves during the second A visit.
  await act(async () => { old.resolve(json({ title: "First A edit" })); await pending; });

  // Then that stale response does not set the new A project's title.
  expect(setProject).not.toHaveBeenCalled();
});
