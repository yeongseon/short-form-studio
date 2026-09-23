import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisualPlanManager } from "../components/creator/useVisualPlanManager";
import { deferred, json, plan, scene } from "./visualPlanFixtures";

const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>();
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); fetchMock.mockResolvedValue(json(plan())); });
afterEach(() => { vi.unstubAllGlobals(); });

async function mount() {
  const hook = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
  await waitFor(() => expect(hook.result.current.visualVersion).toBe(1));
  return hook;
}

describe("visual drafts during refresh and save", () => {
  it("retains a submitted field when a successful response did not acknowledge it", async () => {
    // Given a dirty scene and a response containing a different server value.
    const { result } = await mount();
    act(() => result.current.onFieldChange("scene-0", "mood", "local mood"));
    fetchMock.mockResolvedValueOnce(json(plan(2)));
    // When the save response does not echo the submitted edit.
    await act(() => result.current.onSaveScene("scene-0"));
    // Then success alone does not clear the local draft.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: "local mood", dirty: true });
  });

  it("preserves edited fields while accepting untouched fields and scenes on refresh", async () => {
    // Given a local prompt and a remote change to that same prompt.
    const { result } = await mount();
    act(() => result.current.onFieldChange("scene-0", "prompt", "local draft"));
    fetchMock.mockResolvedValue(json(plan(2, [
      { ...scene(), prompt: "remote conflict", mood: "remote mood", generation_status: "completed" },
      scene("scene-1", "fresh sibling"),
    ])));
    // When an active generation poll refreshes the plan.
    await act(() => result.current.refreshVisualPlan());
    // Then only locally edited fields win; freshness is not frozen.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({
      prompt: "local draft", dirty: true, mood: "remote mood", generation_status: "completed",
    });
    expect(result.current.visualFieldBySceneId["scene-1"].prompt).toBe("fresh sibling");
    expect(result.current.visualVersion).toBe(2);
  });

  it("clears only acknowledged edits and retains sibling and in-flight edits", async () => {
    // Given two dirty scenes and a pending save of A.
    const { result } = await mount();
    act(() => {
      result.current.onFieldChange("scene-0", "prompt", "submitted");
      result.current.onFieldChange("scene-1", "mood", "local sibling");
    });
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise);
    let saving: Promise<void>;
    act(() => { saving = result.current.onSaveScene("scene-0"); });
    act(() => result.current.onFieldChange("scene-0", "prompt", "typed later"));
    // When the earlier snapshot is acknowledged.
    await act(async () => {
      pending.resolve(json(plan(2, [{ ...scene(), prompt: "submitted", prompt_source: "user_edited", prompt_edited: true }, scene("scene-1")])));
      await saving;
    });
    // Then neither the subsequent draft nor B is lost.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ prompt: "typed later", dirty: true, saving: false });
    expect(result.current.visualFieldBySceneId["scene-1"]).toMatchObject({ mood: "local sibling", dirty: true });
  });

  it("acknowledges a saved scene without replacing another dirty scene", async () => {
    // Given independent edits.
    const { result } = await mount();
    act(() => {
      result.current.onFieldChange("scene-0", "mood", "saved mood");
      result.current.onFieldChange("scene-1", "composition", "unsaved frame");
    });
    fetchMock.mockResolvedValueOnce(json(plan(2, [{ ...scene(), mood: "saved mood" }, scene("scene-1")])));
    // When only A is saved.
    await act(() => result.current.onSaveScene("scene-0"));
    // Then only A is clean.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: "saved mood", dirty: false });
    expect(result.current.visualFieldBySceneId["scene-1"]).toMatchObject({ composition: "unsaved frame", dirty: true });
  });

  it.each([409, 500])("keeps a failed %s save dirty with versioned wire contract", async (status) => {
    // Given a refreshed version and an edited prompt.
    const { result } = await mount();
    act(() => result.current.onFieldChange("scene-0", "prompt", "local draft"));
    fetchMock.mockResolvedValueOnce(json(plan(3)));
    await act(() => result.current.refreshVisualPlan());
    fetchMock.mockResolvedValueOnce(json({ detail: "Save rejected" }, status));
    // When the server rejects the save.
    await act(() => result.current.onSaveScene("scene-0"));
    // Then no automatic retry or acknowledgement occurs.
    expect(JSON.parse(String(fetchMock.mock.lastCall?.[1]?.body))).toMatchObject({ prompt: "local draft", expected_version: 3 });
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ prompt: "local draft", dirty: true, saving: false });
    expect(result.current.visualError).toBe("Save rejected");
  });
});
