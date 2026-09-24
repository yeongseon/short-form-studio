import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRunActions } from "../pages/project/useRunActions";
import { useMediaActions } from "../components/creator/useMediaActions";
import type { ProjectDetail, RunDetail } from "../pages/project/types";
import type { StoryboardResponse } from "../api/storyboard";

afterEach(() => { vi.unstubAllGlobals(); });

const a = { id: 1, title: "A" } as ProjectDetail;
const b = { id: 2, title: "B" } as ProjectDetail;
const runA = { id: 11, project_id: 1, current_stage: "SCRIPT_REVIEW" } as RunDetail;
const runB = { id: 22, project_id: 2, current_stage: "SCRIPT_REVIEW" } as RunDetail;

function renderRunActions() {
  const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>()
    .mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const refreshRun = vi.fn(async () => {});
  const setProject = vi.fn<Parameters<React.Dispatch<React.SetStateAction<ProjectDetail | null>>>, void>();
  const navigate = vi.fn<[string], void>();
  const hook = renderHook(({ project, run, projectId }) => useRunActions({
    run, project, numericProjectId: projectId, modelSelection: {}, setProject, refreshRun, navigate,
  }), { initialProps: { project: a, run: runA, projectId: 1 } });
  return { fetchMock, refreshRun, navigate, hook };
}

it.each([
  "handleApprove", "handleGenerate", "handleRestart", "handleGoBack",
  "handleApproveVisualPlan", "handleGenerateVisualPlan", "handleRestartVisualPlan",
  "handleRender", "handleApproveFinal", "handleStop", "handleResume", "handleDeleteProject",
] as const)("a %s callback captured for A sends nothing after B is active", async (action) => {
  // Given a handler captured while A was displayed.
  const { fetchMock, refreshRun, navigate, hook } = renderRunActions();
  const stale = hook.result.current[action];
  hook.rerender({ project: b, run: runB, projectId: 2 });

  // When the old callback is invoked from B's view.
  await act(async () => { await stale(); });

  // Then no request mutates A and B's view is untouched.
  expect(fetchMock).not.toHaveBeenCalled();
  expect(refreshRun).not.toHaveBeenCalled();
  expect(navigate).not.toHaveBeenCalled();
  expect(hook.result.current.toast).toBeNull();
});

it("a title save captured for A does not rename A after B is active", async () => {
  // Given a dirty title draft for A and its save handler.
  const { fetchMock, hook } = renderRunActions();
  act(() => { hook.result.current.setTitleDraft("A renamed"); });
  const stale = hook.result.current.handleTitleSave;
  hook.rerender({ project: b, run: runB, projectId: 2 });

  // When the old save runs.
  await act(async () => { await stale(); });

  // Then no PATCH is sent and no save spinner is shown for B.
  expect(fetchMock).not.toHaveBeenCalled();
  expect(hook.result.current.savingTitle).toBe(false);
});

it.each([
  ["onGenerateImage", (h: ReturnType<typeof useMediaActions>) => h.onGenerateImage("scene-1")],
  ["onGenerateAudio", (h: ReturnType<typeof useMediaActions>) => h.onGenerateAudio("1")],
  ["onGenerateSubtitles", (h: ReturnType<typeof useMediaActions>) => h.onGenerateSubtitles("1")],
  ["onBulkImages", (h: ReturnType<typeof useMediaActions>) => h.onBulkImages()],
  ["onBulkAudio", (h: ReturnType<typeof useMediaActions>) => h.onBulkAudio()],
  ["onBulkSubtitles", (h: ReturnType<typeof useMediaActions>) => h.onBulkSubtitles()],
] as const)("a %s callback captured for run A sends nothing after run B is active", async (_name, invoke) => {
  // Given media actions captured for run A.
  const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>()
    .mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const onStatusMessage = vi.fn<[string | null], void>();
  const setStoryboard = vi.fn<Parameters<React.Dispatch<React.SetStateAction<StoryboardResponse | null>>>, void>();
  const hook = renderHook(({ runId }) => useMediaActions({
    runId, storyboard: null, setStoryboard, onStatusMessage,
  }), { initialProps: { runId: 11 } });
  const stale = hook.result.current;
  hook.rerender({ runId: 22 });

  // When the old callback fires.
  await act(async () => { await invoke(stale); });

  // Then no request or status update happens.
  expect(fetchMock).not.toHaveBeenCalled();
  expect(onStatusMessage).not.toHaveBeenCalled();
  expect(setStoryboard).not.toHaveBeenCalled();
  expect(hook.result.current.bulkGenerating).toBe(false);
});
