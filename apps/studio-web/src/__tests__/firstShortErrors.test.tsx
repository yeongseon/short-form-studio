import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { apiJson, apiVoid } from "../api/client";
import ProgressDialog from "../components/creator/ProgressDialog";

afterEach(() => { vi.restoreAllMocks(); });

describe("unknown API error boundary", () => {
  it.each([apiJson, apiVoid])("parses the actual demo 409 detail object", async (request) => {
    // Given the real prerequisite response shape.
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      detail: { error: "demo prerequisites not configured", plan: { ready: false } },
    }), { status: 409 }));
    // When either client consumes the response, Then only text crosses into UI state.
    await expect(request("/demo")).rejects.toMatchObject({
      status: 409, detail: "demo prerequisites not configured",
    });
  });

  it.each([null, [], 42, { detail: ["invalid"] }, { detail: { error: {} } }])(
    "uses a textual fallback for malformed response %j", async (body) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status: 400 }));
      await expect(apiJson("/demo")).rejects.toMatchObject({ detail: "Request failed (400)" });
    },
  );

  it("filters non-string recovery steps", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      detail: "Unavailable", error: { recovery_steps: ["Retry", {}, null, 3] },
    }), { status: 503 }));
    await expect(apiJson("/demo")).rejects.toMatchObject({ recoverySteps: ["Retry"] });
  });
});

it("shows the newest task failure from a newest-first task response", async () => {
  // Given descending task ids, with distinct historical failure data.
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const body = url.endsWith("/tasks") ? [
      { id: 91, task_type: "render_video", attempt: 1, status: "failed", error_code: "provider_error", error_message: "Newest failure", failure: { code: "PROVIDER", category: "PROVIDER", retryable: true, message: "Newest failure", recovery_steps: ["Retry latest render"] } },
      { id: 12, task_type: "generate_script", attempt: 5, status: "failed", error_code: "provider_timeout", error_message: "Historical failure" },
    ] : { current_stage: "RENDER_GENERATING", status: "failed" };
    return new Response(JSON.stringify(body));
  });
  // When the progress dialog polls, Then it displays only current recovery guidance.
  render(<ProgressDialog open runId={7} expectedStage="RENDER_GENERATING" />);
  expect(await screen.findByText("Retry latest render")).toBeInTheDocument();
  expect(screen.queryByText("Historical failure")).not.toBeInTheDocument();
});
