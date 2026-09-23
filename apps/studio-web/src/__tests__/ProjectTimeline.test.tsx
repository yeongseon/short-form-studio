import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import ProjectPage from "../pages/ProjectPage";

afterEach(() => { vi.restoreAllMocks(); });

function setup(stage = "TIMELINE_REVIEW", approvalStatus = 200, previewRevision: unknown = 11) {
  const run = { id: 31, project_id: 72, current_stage: stage, status: stage === "TIMELINE_REVIEW" ? "paused" : "running", model_defaults: {}, metadata: { render_source: "timeline" } };
  const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    let body: unknown = {};
    if (url.endsWith("/approve-timeline-render")) {
      return new Response(JSON.stringify(approvalStatus === 409
        ? { detail: { error: "Timeline revision changed", plan: {} } }
        : { ...run, current_stage: "RENDER_GENERATING" }), { status: approvalStatus });
    }
    if (url.endsWith("/projects/72")) body = { id: 72, title: "Saved sample", source_type: "idea", status: "active" };
    else if (url.endsWith("/projects/72/runs")) body = { runs: [run], total: 1 };
    else if (url.endsWith("/timeline")) body = { id: "tl-72", project_id: 72, revision: 8, segments: [{ id: "s1" }] };
    else if (url.includes("/timeline/preview?")) body = { timeline_revision: previewRevision, segments: [{ kind: "image", source: "workspaces/7/assets/sample.png", media_url: "/api/creator/projects/72/assets/9/content", timeline_start_seconds: 0, duration_seconds: 5, fit_mode: "cover" }], output_spec: { width: 1080, height: 1920, fps: 30 }, encoding_profile: { name: "preview" } };
    else if (url.endsWith("/runs/31")) body = { ...run, current_stage: "RENDER_GENERATING" };
    else if (url.endsWith("/preview")) body = { video: { path: "output.mp4" } };
    else if (url.endsWith("/models")) body = { script_models: [], image_models: [], tts_models: [], stt_models: [] };
    else if (url.endsWith("/storyboard")) body = { paragraphs: [], total_paragraphs: 0, ready_paragraphs: 0 };
    else if (url.endsWith("/script/structured")) return new Response("{}", { status: 404 });
    void init;
    return new Response(JSON.stringify(body));
  });
  render(<MemoryRouter initialEntries={["/projects/72"]}><Routes>
    <Route path="/projects/:projectId" element={<ProjectPage />} />
  </Routes></MemoryRouter>);
  return spy;
}

it("does not show the empty state when a timeline run exists", async () => {
  setup();
  await screen.findByDisplayValue("Saved sample");
  expect(screen.queryByTestId("no-run")).not.toBeInTheDocument();
});

it("previews the saved timeline before explicitly approving its revision once", async () => {
  const spy = setup();
  const media = await screen.findByTestId("preview-media");
  expect(media).toHaveAttribute("src", "/api/creator/projects/72/assets/9/content");
  const approve = await screen.findByRole("button", { name: "Approve timeline & render" });
  expect(approve).toBeDisabled();
  fireEvent.load(media);
  await waitFor(() => expect(approve).toBeEnabled());
  expect(spy.mock.calls.filter(([url]) => String(url).endsWith("/approve-timeline-render"))).toHaveLength(0);
  act(() => { fireEvent.click(approve); fireEvent.click(approve); });
  await waitFor(() => expect(spy.mock.calls.filter(([url]) => String(url).endsWith("/approve-timeline-render"))).toHaveLength(1));
  const call = spy.mock.calls.find(([url]) => String(url).endsWith("/approve-timeline-render"));
  expect(call?.[1]).toMatchObject({ method: "POST", body: JSON.stringify({ expected_revision: 11 }) });
  expect(spy.mock.calls.some(([url]) => String(url).endsWith("/timeline"))).toBe(false);
});

it("keeps revision conflicts visible instead of auto-approving a newer timeline", async () => {
  setup("TIMELINE_REVIEW", 409);
  const approve = await screen.findByRole("button", { name: "Approve timeline & render" });
  fireEvent.load(await screen.findByTestId("preview-media"));
  await waitFor(() => expect(approve).toBeEnabled());
  fireEvent.click(approve);
  expect(await screen.findByRole("alert")).toHaveTextContent("Timeline revision changed");
});

it("keeps approval disabled until media loads even after the preview JSON arrives", async () => {
  const spy = setup();
  await screen.findByTestId("preview-media");
  const approve = screen.getByRole("button", { name: "Approve timeline & render" });
  fireEvent.click(approve);
  expect(approve).toBeDisabled();
  expect(spy.mock.calls.some(([url]) => String(url).endsWith("/approve-timeline-render"))).toBe(false);
});

it("revokes approval readiness when preview media fails", async () => {
  const spy = setup();
  const media = await screen.findByTestId("preview-media");
  fireEvent.load(media);
  const approve = screen.getByRole("button", { name: "Approve timeline & render" });
  expect(approve).toBeEnabled();
  fireEvent.error(media);
  expect(approve).toBeDisabled();
  expect(await screen.findByRole("alert")).toHaveTextContent(/reload/i);
  fireEvent.click(approve);
  expect(spy.mock.calls.some(([url]) => String(url).endsWith("/approve-timeline-render"))).toBe(false);
});

it.each([null, "11", -1, 1.5])("refuses approval without a valid preview revision (%s)", async (revision) => {
  setup("TIMELINE_REVIEW", 200, revision);
  fireEvent.load(await screen.findByTestId("preview-media"));
  expect(screen.getByRole("button", { name: "Approve timeline & render" })).toBeDisabled();
  expect(await screen.findByRole("alert")).toHaveTextContent(/revision/i);
});

it("preserves final review navigation for timeline-backed runs", async () => {
  setup("FINAL_REVIEW");
  expect(await screen.findByTestId("review-link")).toHaveAttribute("href", "/review/31");
  expect(screen.queryByRole("button", { name: "Approve timeline & render" })).not.toBeInTheDocument();
});

it("requires timeline approval rather than offering generic resume at its review gate", async () => {
  setup();
  await screen.findByDisplayValue("Saved sample");
  expect(screen.queryByRole("button", { name: /Resume/ })).not.toBeInTheDocument();
});
