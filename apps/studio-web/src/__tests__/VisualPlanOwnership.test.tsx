import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisualPlanManager } from "../components/creator/useVisualPlanManager";
import { deferred, json, plan, scene } from "./visualPlanFixtures";

const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>();
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); fetchMock.mockImplementation(async () => json(plan())); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("visual plan request ownership", () => {
  it("ignores mutation feedback after unmount", async () => {
    // Given a pending save in a mounted hook.
    const status = vi.fn();
    const { result, unmount } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW", status));
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => result.current.onFieldChange("scene-0", "mood", "draft"));
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise);
    let saving: Promise<void>;
    act(() => { saving = result.current.onSaveScene("scene-0"); });
    unmount();
    // When the mutation fails after unmount.
    await act(async () => { pending.resolve(json({ detail: "Late error" }, 500)); await saving; });
    // Then obsolete feedback is not delivered to the parent.
    expect(status).not.toHaveBeenCalled();
  });

  it.each(["refresh", "save"] as const)("isolates drafts when an old run's %s completes last", async (operation) => {
    // Given a dirty run with a pending request.
    const status = vi.fn();
    const { result, rerender } = renderHook(({ runId }) => useVisualPlanManager(runId, "VISUAL_PLAN_REVIEW", status), { initialProps: { runId: 1 } });
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => result.current.onFieldChange("scene-0", "prompt", "old draft"));
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise);
    let request: Promise<void>;
    act(() => { request = operation === "save" ? result.current.onSaveScene("scene-0") : result.current.refreshVisualPlan(); });
    fetchMock.mockImplementation(async () => json(plan(8, [scene("scene-0", "new run")])));
    rerender({ runId: 2 });
    await waitFor(() => expect(result.current.visualVersion).toBe(8));
    // When the previous run responds after navigation.
    await act(async () => { pending.resolve(json(plan(9, [scene("scene-0", "old response")]))); await request; });
    // Then the new run owns all visible state and status callbacks.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ prompt: "new run", dirty: false, saving: false });
    expect(result.current.visualVersion).toBe(8);
    expect(status).not.toHaveBeenCalled();
  });

  it("discards late polling responses after a newer refresh", async () => {
    // Given two overlapping reads.
    const { result } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    const older = deferred<Response>();
    fetchMock.mockReturnValueOnce(older.promise);
    let request: Promise<void>;
    act(() => { request = result.current.refreshVisualPlan(); });
    fetchMock.mockImplementation(async () => json(plan(3, [scene("scene-0", "new response")])));
    await act(() => result.current.refreshVisualPlan());
    // When the older request completes.
    await act(async () => { older.resolve(json(plan(2))); await request; });
    // Then freshness does not regress.
    expect(result.current.visualVersion).toBe(3);
    expect(result.current.visualFieldBySceneId["scene-0"].prompt).toBe("new response");
  });

  it("invalidates pending saves and drafts when leaving the visual flow", async () => {
    // Given a save pending during a stage reset.
    const { result, rerender } = renderHook(({ stage }) => useVisualPlanManager(1, stage), { initialProps: { stage: "VISUAL_PLAN_REVIEW" } });
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => result.current.onFieldChange("scene-0", "prompt", "old draft"));
    const pending = deferred<Response>();
    fetchMock.mockReturnValueOnce(pending.promise);
    let saving: Promise<void>;
    act(() => { saving = result.current.onSaveScene("scene-0"); });
    rerender({ stage: "SCRIPT_REVIEW" });
    // When the old mutation completes after reset.
    await act(async () => { pending.resolve(json(plan(2))); await saving; });
    // Then it cannot restore the discarded draft/session.
    expect(result.current.visualFieldBySceneId).toEqual({});
    expect(result.current.visualVersion).toBeNull();
  });
});
