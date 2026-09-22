import { describe, it, expect, vi, afterEach } from "vitest";
import {
  createDemoRun,
  getDemoPlan,
  getDefaultWorkspaceId,
  getOnboarding,
  getProviderConfig,
  startDemoShort,
} from "../api/demo";

function okResponse(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("demo/onboarding/provider-config API wrappers", () => {
  it("createDemoRun POSTs to the workspace-scoped seed route and returns seeded ids", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        okResponse({ run: { project_id: 202 }, seeded_project_id: 202, timeline_id: "demo-timeline", plan: {} }),
      );
    const result = await createDemoRun(7);
    const [url, init] = spy.mock.calls[0];
    expect(String(url)).toContain("/workspaces/7/demo-short/runs");
    expect(init?.method).toBe("POST");
    expect(result.seeded_project_id).toBe(202);
    expect(result.timeline_id).toBe("demo-timeline");
  });

  it("getDemoPlan GETs the project-scoped plan route", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(okResponse({ ready: true }));
    await getDemoPlan(5);
    expect(String(spy.mock.calls[0][0])).toContain("/projects/5/demo-short/plan");
  });

  it("getOnboarding GETs the workspace onboarding route", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(okResponse({ is_first_run: true }));
    await getOnboarding(7);
    expect(String(spy.mock.calls[0][0])).toContain("/workspaces/7/onboarding");
  });

  it("getProviderConfig GETs the provider-config route", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(okResponse({ providers: [] }));
    await getProviderConfig();
    expect(String(spy.mock.calls[0][0])).toContain("/models/provider-config");
  });

  it("getDefaultWorkspaceId returns the first workspace from membership", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      okResponse({ workspaces: [{ id: 7, name: "ws" }, { id: 9 }] }),
    );
    expect(await getDefaultWorkspaceId()).toBe(7);
  });

  it("startDemoShort resolves the workspace then seeds a run against it", async () => {
    const spy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(okResponse({ workspaces: [{ id: 7 }] }))
      .mockResolvedValueOnce(
        okResponse({ run: { project_id: 202 }, seeded_project_id: 202, timeline_id: "demo-timeline", plan: {} }),
      );
    const result = await startDemoShort();
    expect(String(spy.mock.calls[1][0])).toContain("/workspaces/7/demo-short/runs");
    expect(result.seeded_project_id).toBe(202);
  });
});
