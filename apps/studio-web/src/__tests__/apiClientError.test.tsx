import { describe, it, expect, vi, afterEach } from "vitest";
import { ApiError, apiJson } from "../api/client";

function mockResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("apiJson error envelope parsing (SF-78)", () => {
  it("parses the structured error envelope into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockResponse(409, {
        detail: "Version conflict for 7: expected 3, actual 5",
        error: {
          code: "VERSION_CONFLICT",
          category: "VERSION_CONFLICT",
          retryable: false,
          recovery_steps: ["Refresh to load the latest revision", "Reapply your change"],
        },
      }),
    );
    const err = await apiJson("/x").then(
      () => null,
      (e: unknown) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    const api = err as ApiError;
    expect(api.status).toBe(409);
    expect(api.detail).toBe("Version conflict for 7: expected 3, actual 5");
    expect(api.category).toBe("VERSION_CONFLICT");
    expect(api.retryable).toBe(false);
    expect(api.recoverySteps).toEqual([
      "Refresh to load the latest revision",
      "Reapply your change",
    ]);
  });

  it("falls back to detail-only when no error envelope is present (legacy)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      mockResponse(400, { detail: "Invalid input" }),
    );
    const err = (await apiJson("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.detail).toBe("Invalid input");
    expect(err.category).toBeUndefined();
    expect(err.retryable).toBeUndefined();
    expect(err.recoverySteps).toBeUndefined();
  });

  it("does not crash on a malformed / non-JSON body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    const err = (await apiJson("/x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(typeof err.detail).toBe("string");
  });
});
