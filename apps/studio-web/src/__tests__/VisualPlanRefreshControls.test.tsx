import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useVisualPlanManager } from "../components/creator/useVisualPlanManager";
import { deferred, json, plan, scene } from "./visualPlanFixtures";

const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>();
beforeEach(() => { vi.stubGlobal("fetch", fetchMock); fetchMock.mockReset(); fetchMock.mockImplementation(async () => json(plan())); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("visual refresh controls", () => {
  it("loads a newly entered visual stage immediately while preserving its drafts", async () => {
    // Given an edited scene in an active generation stage.
    const { result, rerender } = renderHook(({ stage }) => useVisualPlanManager(1, stage), { initialProps: { stage: "VISUAL_ASSET_GENERATING" } });
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => result.current.onFieldChange("scene-0", "mood", "local mood"));
    fetchMock.mockImplementation(async () => json(plan(2, [{ ...scene(), generation_status: "completed" }])));
    // When the run enters its review stage and generation polling stops.
    rerender({ stage: "VISUAL_ASSET_REVIEW" });
    // Then the final server state loads without discarding edits.
    await waitFor(() => expect(result.current.visualVersion).toBe(2));
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: "local mood", dirty: true, generation_status: "completed" });
  });

  it("clears a transient load error on successful refresh", async () => {
    // Given a failed initial load.
    fetchMock.mockResolvedValueOnce(json({ detail: "Temporary read failure" }, 500));
    const { result } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
    await waitFor(() => expect(result.current.visualError).toBe("Temporary read failure"));
    // When a subsequent poll succeeds.
    await act(() => result.current.refreshVisualPlan());
    // Then the stale read error disappears.
    expect(result.current.visualError).toBeNull();
    expect(result.current.visualVersion).toBe(1);
  });

  it("retains a save conflict across successful polls", async () => {
    // Given a rejected save.
    const { result } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => result.current.onFieldChange("scene-0", "mood", "local mood"));
    fetchMock.mockResolvedValueOnce(json({ detail: "Version conflict" }, 409));
    await act(() => result.current.onSaveScene("scene-0"));
    // When polling succeeds without acknowledging the mutation.
    await act(() => result.current.refreshVisualPlan());
    // Then the user still sees conflict guidance and the draft.
    expect(result.current.visualError).toBe("Version conflict");
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: "local mood", dirty: true });
  });

  it("ignores a pre-save poll that resolves after acknowledgement", async () => {
    // Given a read snapshot older than a completed mutation.
    const { result } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    const poll = deferred<Response>();
    fetchMock.mockReturnValueOnce(poll.promise);
    let reading: Promise<void>;
    act(() => { reading = result.current.refreshVisualPlan(); });
    act(() => result.current.onFieldChange("scene-0", "mood", "saved mood"));
    fetchMock.mockResolvedValueOnce(json(plan(2, [{ ...scene(), mood: "saved mood" }])));
    await act(() => result.current.onSaveScene("scene-0"));
    // When the stale poll completes.
    await act(async () => { poll.resolve(json(plan())); await reading; });
    // Then the acknowledged server version remains visible.
    expect(result.current.visualVersion).toBe(2);
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: "saved mood", dirty: false });
  });

  it("keeps absent-plan drafts and nullable or array edits until explicit save", async () => {
    // Given edited metadata.
    const { result } = renderHook(() => useVisualPlanManager(1, "VISUAL_PLAN_REVIEW"));
    await waitFor(() => expect(result.current.visualVersion).toBe(1));
    act(() => {
      result.current.onFieldChange("scene-0", "mood", "  ");
      result.current.onFieldChange("scene-0", "style_tags", "one, two, ");
    });
    fetchMock.mockResolvedValueOnce(json({ detail: "No visual plan" }, 404));
    // When a transient missing-plan result arrives.
    await act(() => result.current.refreshVisualPlan());
    // Then the local fields remain dirty.
    expect(result.current.visualFieldBySceneId["scene-0"]).toMatchObject({ mood: null, style_tags: ["one", "two"], dirty: true });
  });
});
