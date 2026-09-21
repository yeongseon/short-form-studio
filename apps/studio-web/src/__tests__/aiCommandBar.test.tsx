import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { AICommandBar } from "../components/creator/aiCommandBar";
import type { AIRequestFn, EditProposal } from "../components/creator/aiCommandBar";

function proposal(commands: string[] = ["trimSegment"]): EditProposal {
  return { commands, summary: `${commands.length} change(s)` };
}

type RequestMock = Mock<[string, AbortSignal], Promise<EditProposal>>;

describe("AICommandBar", () => {
  const onUnhandled = (e: PromiseRejectionEvent) => e.preventDefault();
  beforeEach(() => window.addEventListener("unhandledrejection", onUnhandled));
  afterEach(() => window.removeEventListener("unhandledrejection", onUnhandled));

  function make(request: AIRequestFn) {
    return new AICommandBar({ request });
  }

  it("starts idle", () => {
    const bar = make(vi.fn() as unknown as RequestMock);
    expect(bar.status).toBe("idle");
    expect(bar.proposal).toBeNull();
  });

  it("rejects an empty request without calling the AI", async () => {
    const request = vi.fn() as unknown as RequestMock;
    const bar = make(request);
    await expect(bar.submit("   ")).rejects.toThrow();
    expect(request).not.toHaveBeenCalled();
    expect(bar.status).toBe("idle");
  });

  it("goes requesting -> proposal on success and never mutates directly", async () => {
    const request = vi.fn(async () => proposal(["trimSegment", "deleteSegment"])) as unknown as RequestMock;
    const bar = make(request);
    const p = bar.submit("make it shorter");
    expect(bar.status).toBe("requesting");
    await p;
    expect(bar.status).toBe("proposal");
    expect(bar.proposal?.commands).toEqual(["trimSegment", "deleteSegment"]);
    // proposal is exposed for validation/diff, NOT applied to any timeline here
    expect(bar.applied).toBe(false);
  });

  it("goes to error on request failure", async () => {
    const request = vi.fn(async () => {
      throw new Error("model unavailable");
    }) as unknown as RequestMock;
    const bar = make(request);
    await bar.submit("x").catch(() => {});
    expect(bar.status).toBe("error");
    expect(bar.error).toContain("model unavailable");
  });

  it("cancels an in-flight request", async () => {
    let sawAbort = false;
    const request = vi.fn(
      (_prompt: string, signal: AbortSignal) =>
        new Promise<EditProposal>((_resolve, reject) => {
          signal.addEventListener("abort", () => {
            sawAbort = true;
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    ) as unknown as RequestMock;
    const bar = make(request);
    const p = bar.submit("slow edit");
    expect(bar.status).toBe("requesting");
    bar.cancel();
    await p.catch(() => {});
    expect(sawAbort).toBe(true);
    expect(bar.status).toBe("idle");
    expect(bar.proposal).toBeNull();
  });

  it("retries after an error", async () => {
    let attempt = 0;
    const request = vi.fn(async () => {
      attempt += 1;
      if (attempt === 1) throw new Error("boom");
      return proposal(["resizeSegment"]);
    }) as unknown as RequestMock;
    const bar = make(request);
    await bar.submit("edit").catch(() => {});
    expect(bar.status).toBe("error");
    await bar.retry();
    expect(bar.status).toBe("proposal");
    expect(bar.proposal?.commands).toEqual(["resizeSegment"]);
  });

  it("requires an explicit apply: apply() emits the proposal to onApply once", async () => {
    const onApply = vi.fn();
    const request = vi.fn(async () => proposal(["trimSegment"])) as unknown as RequestMock;
    const bar = new AICommandBar({ request, onApply });
    await bar.submit("edit");
    expect(onApply).not.toHaveBeenCalled();
    bar.apply();
    expect(onApply).toHaveBeenCalledWith(proposal(["trimSegment"]));
    expect(bar.applied).toBe(true);
    // a second apply is a no-op (proposal already applied)
    bar.apply();
    expect(onApply).toHaveBeenCalledTimes(1);
  });

  it("apply before a proposal exists throws", () => {
    const bar = make(vi.fn() as unknown as RequestMock);
    expect(() => bar.apply()).toThrow();
  });

  it("dismiss clears the proposal back to idle without applying", async () => {
    const onApply = vi.fn();
    const request = vi.fn(async () => proposal()) as unknown as RequestMock;
    const bar = new AICommandBar({ request, onApply });
    await bar.submit("edit");
    bar.dismiss();
    expect(bar.status).toBe("idle");
    expect(bar.proposal).toBeNull();
    expect(onApply).not.toHaveBeenCalled();
  });

  it("notifies subscribers of status changes", async () => {
    const request = vi.fn(async () => proposal()) as unknown as RequestMock;
    const bar = make(request);
    const seen: string[] = [];
    bar.subscribe((s) => seen.push(s.status));
    await bar.submit("edit");
    expect(seen).toContain("requesting");
    expect(seen).toContain("proposal");
  });
});
