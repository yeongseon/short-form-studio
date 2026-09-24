import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UnifiedSceneWorkspace from "../components/creator/UnifiedSceneWorkspace";
import { deferred, json, plan, scene, storyboard } from "./visualPlanFixtures";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("mounted workspace generation polling", () => {
  it("ignores an old run storyboard arriving after navigation", async () => {
    // Given run A's storyboard request is pending when the workspace switches to B.
    const old = deferred<Response>();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/runs/1/storyboard")) return old.promise;
      if (url.endsWith("/runs/2/storyboard")) return json({ ...storyboard(), run_id: 2, paragraphs: [] });
      return json(plan());
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<UnifiedSceneWorkspace runId={1} currentStage="SCRIPT_REVIEW" />);
    view.rerender(<UnifiedSceneWorkspace runId={2} currentStage="SCRIPT_REVIEW" />);
    await act(async () => { await Promise.resolve(); });
    // When A's response arrives after B.
    await act(async () => { old.resolve(json(storyboard())); });
    // Then run A's scenes are not displayed in B's workspace.
    expect(screen.queryByTestId("scene-card-sec-0")).not.toBeInTheDocument();
  });
  it("retains the editor value and dirty indicator across the actual 4s timer while assets update", async () => {
    // Given the real workspace, real hook/client and an active generation paragraph.
    vi.useFakeTimers();
    let currentPlan = plan();
    const board = storyboard();
    const fetchMock = vi.fn<Parameters<typeof fetch>, ReturnType<typeof fetch>>().mockImplementation(async (input) =>
      json(String(input).endsWith("/storyboard") ? board : currentPlan));
    vi.stubGlobal("fetch", fetchMock);
    render(<UnifiedSceneWorkspace runId={1} currentStage="VISUAL_PLAN_REVIEW" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    fireEvent.click(screen.getByTestId("scene-visual-toggle-sec-0"));
    fireEvent.change(screen.getByLabelText("Prompt"), { target: { value: "unsaved local prompt" } });
    currentPlan = plan(2, [scene(), scene("scene-1", "new server prompt")]);
    board.paragraphs[1] = { ...board.paragraphs[1], image_url: "/image.png", image_asset_id: 42, status: "idle" };
    // When the workspace's default polling timer fires.
    await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
    // Then edits remain and unrelated generation results arrive.
    expect(screen.getByLabelText("Prompt")).toHaveValue("unsaved local prompt");
    expect(screen.getByTestId("scene-visual-dirty-sec-0")).toHaveTextContent("Unsaved changes");
    expect(screen.getByTestId("scene-image-prompt-sec-1")).toHaveValue("new server prompt");
    expect(screen.getByTestId("scene-image-sec-1")).toHaveAttribute("src", "/api/creator/runs/1/visual-assets/42/content");
    expect(screen.getByTestId("scene-badge-sec-1")).toHaveTextContent("Partial");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });
});
