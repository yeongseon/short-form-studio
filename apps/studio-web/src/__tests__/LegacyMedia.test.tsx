import { expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LegacyReviewSections } from "../pages/review/LegacyReviewSections";

it("mounts legacy historical assets by identity rather than storage path", () => {
  render(<MemoryRouter><LegacyReviewSections
    run={{ id: 7, project_id: 3, current_stage: "VISUAL_ASSET_REVIEW", status: "paused", restart_from: null, model_defaults: null }}
    script={null} scenes={[]} assets={{ "scene-1": [{ id: 11, asset_path: "data/artifacts/7/image.png", model_used: "test", is_active: true }] }}
  /></MemoryRouter>);
  expect(screen.getByRole("img")).toHaveAttribute("src", "/api/creator/runs/7/visual-assets/11/content");
});
