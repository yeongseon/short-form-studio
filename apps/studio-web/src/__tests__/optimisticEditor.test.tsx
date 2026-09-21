import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { OptimisticEditor } from "../components/creator/optimisticEditor";
import type { ReconcileResult } from "../components/creator/optimisticEditor";

interface FakeTimeline {
  revision: number;
  segments: string[];
}

function base(revision = 1, segments: string[] = []): FakeTimeline {
  return { revision, segments };
}

/** A local prediction: append a marker to segments (pure, no revision change). */
function add(marker: string) {
  return (t: FakeTimeline): FakeTimeline => ({ ...t, segments: [...t.segments, marker] });
}

describe("OptimisticEditor", () => {
  const onUnhandled = (e: PromiseRejectionEvent) => e.preventDefault();
  beforeEach(() => window.addEventListener("unhandledrejection", onUnhandled));
  afterEach(() => window.removeEventListener("unhandledrejection", onUnhandled));

  function make() {
    return new OptimisticEditor<FakeTimeline>({ initial: base(1, []) });
  }

  it("updates present promptly from a local command (optimistic)", () => {
    const e = make();
    const id = e.applyLocal(add("a"));
    expect(e.present.segments).toEqual(["a"]);
    expect(e.pendingCount).toBe(1);
    expect(typeof id).toBe("string");
  });

  it("stacks multiple optimistic edits", () => {
    const e = make();
    e.applyLocal(add("a"));
    e.applyLocal(add("b"));
    expect(e.present.segments).toEqual(["a", "b"]);
    expect(e.pendingCount).toBe(2);
  });

  it("confirms an accepted edit and adopts the server revision", () => {
    const e = make();
    const id = e.applyLocal(add("a"));
    const result: ReconcileResult = e.confirm(id, { revision: 2, segments: ["a"] });
    expect(result.status).toBe("confirmed");
    expect(e.base.revision).toBe(2);
    expect(e.pendingCount).toBe(0);
    expect(e.present.segments).toEqual(["a"]);
  });

  it("rebases remaining pending edits onto the confirmed server state", () => {
    const e = make();
    const id1 = e.applyLocal(add("a"));
    e.applyLocal(add("b"));
    // server confirms the first edit as revision 2 with segments ["a"]
    e.confirm(id1, { revision: 2, segments: ["a"] });
    // the still-pending "b" edit is replayed on top of the new base
    expect(e.present.segments).toEqual(["a", "b"]);
    expect(e.base.revision).toBe(2);
    expect(e.pendingCount).toBe(1);
  });

  it("rolls back a rejected edit while preserving unrelated edits", () => {
    const e = make();
    const id1 = e.applyLocal(add("a"));
    e.applyLocal(add("b"));
    // server rejects the first edit -> drop it, replay the rest on base
    const result = e.reject(id1);
    expect(result.status).toBe("rolled_back");
    expect(e.present.segments).toEqual(["b"]);
    expect(e.pendingCount).toBe(1);
  });

  it("surfaces a conflict without losing unrelated edits", () => {
    const e = make();
    const id1 = e.applyLocal(add("a"));
    e.applyLocal(add("b"));
    // server reports a conflict on the first edit with an authoritative state
    const result = e.conflict(id1, { revision: 5, segments: ["x"] });
    expect(result.status).toBe("conflict");
    expect(e.base.revision).toBe(5);
    // the conflicting edit is dropped, unrelated pending edits replay on the new base
    expect(e.present.segments).toEqual(["x", "b"]);
    expect(e.pendingCount).toBe(1);
  });

  it("keeps history coherent: confirming out of order still reconciles", () => {
    const e = make();
    const id1 = e.applyLocal(add("a"));
    const id2 = e.applyLocal(add("b"));
    // confirm the SECOND edit first (out-of-order server acceptance)
    e.confirm(id2, { revision: 2, segments: ["a", "b"] });
    // id1 still pending; base advanced; present reflects confirmed server + remaining
    expect(e.base.revision).toBe(2);
    expect(e.pendingCount).toBe(1);
    // confirming id1 now is a no-op reconcile (already absorbed) -> stale
    const late = e.confirm(id1, { revision: 2, segments: ["a", "b"] });
    expect(late.status).toBe("stale");
    expect(e.pendingCount).toBe(0);
  });

  it("rejects an unknown edit id as stale", () => {
    const e = make();
    const result = e.confirm("nonexistent", { revision: 2, segments: [] });
    expect(result.status).toBe("stale");
  });

  it("reconnect() replays all pending edits on the current base", () => {
    const e = make();
    e.applyLocal(add("a"));
    e.applyLocal(add("b"));
    // simulate a fresh authoritative base after reconnect
    const reconciled = e.reconnect({ revision: 4, segments: ["server"] });
    expect(reconciled.segments).toEqual(["server", "a", "b"]);
    expect(e.base.revision).toBe(4);
    expect(e.pendingCount).toBe(2);
  });

  it("notifies subscribers on optimistic apply and reconcile", () => {
    const e = make();
    const seen: number[] = [];
    e.subscribe((state) => seen.push(state.pendingCount));
    const id = e.applyLocal(add("a"));
    e.confirm(id, { revision: 2, segments: ["a"] });
    expect(seen).toEqual([1, 0]);
  });
});
