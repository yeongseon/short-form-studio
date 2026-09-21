import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { Autosave } from "../components/creator/autosave";
import type { SaveResult, SaveTimelineFn } from "../components/creator/autosave";

interface FakeTimeline {
  id: string;
  revision: number;
  segments: unknown[];
}

type SaveMock = Mock<[FakeTimeline, number], Promise<SaveResult<FakeTimeline>>>;

function tl(revision: number, segments: unknown[] = [{ id: "s1" }]): FakeTimeline {
  return { id: "tl-1", revision, segments };
}

describe("Autosave", () => {
  const onUnhandled = (e: PromiseRejectionEvent) => e.preventDefault();
  beforeEach(() => {
    vi.useFakeTimers();
    window.addEventListener("unhandledrejection", onUnhandled);
  });
  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
    window.removeEventListener("unhandledrejection", onUnhandled);
  });

  function make(save: SaveTimelineFn<FakeTimeline>, debounceMs = 500) {
    return new Autosave<FakeTimeline>({
      save,
      debounceMs,
      initialRevision: 1,
    });
  }

  it("starts idle", () => {
    const a = make(vi.fn());
    expect(a.status).toBe("idle");
  });

  it("debounces rapid edits into a single save", async () => {
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => ({ ok: true, timeline: tl(2) })) as unknown as SaveMock;
    const a = make(save);
    a.schedule(tl(1, [{ id: "a" }]));
    a.schedule(tl(1, [{ id: "b" }]));
    a.schedule(tl(1, [{ id: "c" }]));
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(500);
    expect(save).toHaveBeenCalledTimes(1);
    // sends the latest edit + the current expected revision
    expect(save.mock.calls[0][0].segments).toEqual([{ id: "c" }]);
    expect(save.mock.calls[0][1]).toBe(1);
  });

  it("transitions idle -> saving -> saved and adopts the bumped revision", async () => {
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => ({ ok: true, timeline: tl(2) }));
    const a = make(save);
    a.schedule(tl(1));
    await vi.advanceTimersByTimeAsync(500);
    expect(a.status).toBe("saved");
    expect(a.revision).toBe(2);
  });

  it("exposes error state and preserves the unsaved edit on failure", async () => {
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => ({ ok: false, kind: "error", message: "network" }));
    const a = make(save);
    a.schedule(tl(1, [{ id: "unsaved" }]));
    await vi.advanceTimersByTimeAsync(500);
    expect(a.status).toBe("error");
    expect(a.pendingTimeline?.segments).toEqual([{ id: "unsaved" }]);
    expect(a.revision).toBe(1);
  });

  it("exposes conflict state on a 409 without overwriting", async () => {
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => ({ ok: false, kind: "conflict", message: "stale" }));
    const a = make(save);
    a.schedule(tl(1, [{ id: "mine" }]));
    await vi.advanceTimersByTimeAsync(500);
    expect(a.status).toBe("conflict");
    expect(a.pendingTimeline?.segments).toEqual([{ id: "mine" }]);
    // revision NOT advanced on conflict (no silent overwrite)
    expect(a.revision).toBe(1);
  });

  it("does not start a second save while one is in flight (no concurrent overwrite)", async () => {
    let resolveFirst: (r: SaveResult<FakeTimeline>) => void = () => {};
    const save = vi.fn(
      () => new Promise<SaveResult<FakeTimeline>>((r) => { resolveFirst = r; }),
    ) as unknown as SaveMock;
    const a = make(save);
    a.schedule(tl(1, [{ id: "first" }]));
    await vi.advanceTimersByTimeAsync(500);
    expect(save).toHaveBeenCalledTimes(1);
    expect(a.status).toBe("saving");
    // another edit arrives mid-flight -> queued, not fired
    a.schedule(tl(1, [{ id: "second" }]));
    await vi.advanceTimersByTimeAsync(500);
    expect(save).toHaveBeenCalledTimes(1);
    // first completes -> the queued edit then saves
    resolveFirst({ ok: true, timeline: tl(2) });
    await vi.advanceTimersByTimeAsync(500);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save.mock.calls[1][0].segments).toEqual([{ id: "second" }]);
    expect(save.mock.calls[1][1]).toBe(2);
  });

  it("ignores an out-of-order stale response", async () => {
    const resolvers: Array<(r: SaveResult<FakeTimeline>) => void> = [];
    const save = vi.fn(
      () => new Promise<SaveResult<FakeTimeline>>((r) => { resolvers.push(r); }),
    ) as unknown as SaveMock;
    const a = make(save);
    a.schedule(tl(1, [{ id: "v1" }]));
    await vi.advanceTimersByTimeAsync(500);
    // force-flush a second save by resolving nothing yet; simulate a superseding save
    a.forceRetry();
    await vi.advanceTimersByTimeAsync(0);
    expect(save).toHaveBeenCalledTimes(2);
    // resolve the SECOND (newest) first
    resolvers[1]({ ok: true, timeline: tl(3) });
    await vi.advanceTimersByTimeAsync(0);
    expect(a.revision).toBe(3);
    // now the stale FIRST response arrives -> must be ignored
    resolvers[0]({ ok: true, timeline: tl(2) });
    await vi.advanceTimersByTimeAsync(0);
    expect(a.revision).toBe(3);
    expect(a.status).toBe("saved");
  });

  it("retries a failed save via forceRetry", async () => {
    let attempt = 0;
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => {
      attempt += 1;
      return attempt === 1
        ? { ok: false, kind: "error", message: "boom" }
        : { ok: true, timeline: tl(2) };
    });
    const a = make(save);
    a.schedule(tl(1));
    await vi.advanceTimersByTimeAsync(500);
    expect(a.status).toBe("error");
    a.forceRetry();
    await vi.advanceTimersByTimeAsync(0);
    expect(a.status).toBe("saved");
    expect(a.revision).toBe(2);
  });

  it("notifies subscribers of status changes", async () => {
    const save = vi.fn(async (): Promise<SaveResult<FakeTimeline>> => ({ ok: true, timeline: tl(2) }));
    const a = make(save);
    const seen: string[] = [];
    a.subscribe((s) => seen.push(s.status));
    a.schedule(tl(1));
    await vi.advanceTimersByTimeAsync(500);
    expect(seen).toContain("saving");
    expect(seen).toContain("saved");
  });
});
