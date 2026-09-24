import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useMediaActions } from "../components/creator/useMediaActions";
import { deferred, json } from "./visualPlanFixtures";
import type { StoryboardResponse } from "../api/storyboard";

afterEach(() => { vi.unstubAllGlobals(); });

it.each(["onGenerateImage", "onBulkImages"] as const)(
  "ignores old %s completion after switching to a new run",
  async (action) => {
    // Given the same scene ID in runs A and B and a pending A mutation.
    const oldResponse = deferred<Response>();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => oldResponse.promise);
    vi.stubGlobal("fetch", fetchMock);
    const setStoryboard = vi.fn<Parameters<React.Dispatch<React.SetStateAction<StoryboardResponse | null>>>, void>();
    const onStatusMessage = vi.fn<[string | null], void>();
    const board = { run_id: 1, paragraphs: [{ scene_id: "shared-scene", section_id: "shared-section", status: "idle" }] } as StoryboardResponse;
    const hook = renderHook(({ runId }) => useMediaActions({
      runId, storyboard: board, setStoryboard, onStatusMessage,
    }), { initialProps: { runId: 1 } });
    let pending: Promise<void> | undefined;
    act(() => { pending = action === "onGenerateImage" ? hook.result.current.onGenerateImage("shared-scene") : hook.result.current.onBulkImages(); });
    hook.rerender({ runId: 2 });

    // When A's response arrives after B becomes the active run.
    await act(async () => { oldResponse.resolve(json({ task_id: "old-task" })); await pending; });

    // Then no A mutation or status crosses into B's storyboard.
    expect(setStoryboard).not.toHaveBeenCalled();
    expect(onStatusMessage).not.toHaveBeenCalled();
    expect(hook.result.current.bulkGenerating).toBe(false);
  },
);

it("does not accept a late A result after navigating A to B and back to A", async () => {
  // Given an old image generation request whose scene ID recurs after navigation.
  const oldResponse = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(() => oldResponse.promise));
  const setStoryboard = vi.fn<Parameters<React.Dispatch<React.SetStateAction<StoryboardResponse | null>>>, void>();
  const onStatusMessage = vi.fn<[string | null], void>();
  const board = { run_id: 1, paragraphs: [{ scene_id: "shared-scene", section_id: "shared-section", status: "idle" }] } as StoryboardResponse;
  const hook = renderHook(({ runId }) => useMediaActions({
    runId, storyboard: board, setStoryboard, onStatusMessage,
  }), { initialProps: { runId: 1 } });
  let pending: Promise<void> | undefined;
  act(() => { pending = hook.result.current.onGenerateImage("shared-scene"); });

  // When run B becomes active and then A returns before the old response arrives.
  hook.rerender({ runId: 2 });
  hook.rerender({ runId: 1 });
  await act(async () => { oldResponse.resolve(json({ task_id: "stale-task" })); await pending; });

  // Then this older A response cannot mutate the newer A view.
  expect(setStoryboard).not.toHaveBeenCalled();
  expect(onStatusMessage).not.toHaveBeenCalled();
});
