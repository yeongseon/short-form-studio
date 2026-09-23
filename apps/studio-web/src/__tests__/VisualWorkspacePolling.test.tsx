import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import UnifiedSceneWorkspace from "../components/creator/UnifiedSceneWorkspace";
import { json, plan, scene, storyboard } from "./visualPlanFixtures";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("mounted workspace generation polling", () => {
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
