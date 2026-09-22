import { API_BASE } from "../types/api";

export { API_BASE };

/**
 * Centralised fetch wrapper for all API calls.
 *
 * Authentication is handled at the infrastructure layer (reverse-proxy or
 * Vite dev-server proxy) — the browser never holds the shared API key.
 * This wrapper exists as a single place to attach future per-request
 * concerns (tracing headers, CSRF tokens, error normalisation, etc.).
 */
export function apiFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return fetch(input, init);
}

/**
 * Error thrown when the API returns a non-2xx response.
 * Exposes the HTTP status and parsed detail message, plus the optional SF-78
 * structured `error` envelope (category / retryability / recovery steps) when
 * the backend provides it, for structured error handling and recovery UX.
 */
export class ApiError extends Error {
  public readonly code?: string;
  public readonly category?: string;
  public readonly retryable?: boolean;
  public readonly recoverySteps?: string[];

  constructor(
    public readonly status: number,
    public readonly detail: string,
    structured?: {
      code?: string;
      category?: string;
      retryable?: boolean;
      recoverySteps?: string[];
    },
  ) {
    super(detail);
    this.name = "ApiError";
    this.code = structured?.code;
    this.category = structured?.category;
    this.retryable = structured?.retryable;
    this.recoverySteps = structured?.recoverySteps;
  }
}

/**
 * Build an ApiError from a parsed (or null) error body, reading the SF-78
 * `error` envelope when present and always preserving the legacy `detail`.
 */
function toApiError(status: number, body: unknown): ApiError {
  const record = (body ?? null) as Record<string, unknown> | null;
  const detail = (record?.detail as string) ?? `Request failed (${status})`;
  const envelope = record?.error as Record<string, unknown> | undefined;
  if (envelope && typeof envelope === "object") {
    const steps = envelope.recovery_steps;
    return new ApiError(status, detail, {
      code: typeof envelope.code === "string" ? envelope.code : undefined,
      category: typeof envelope.category === "string" ? envelope.category : undefined,
      retryable: typeof envelope.retryable === "boolean" ? envelope.retryable : undefined,
      recoverySteps: Array.isArray(steps) ? (steps as string[]) : undefined,
    });
  }
  return new ApiError(status, detail);
}

/**
 * Typed JSON fetch helper — consolidates the repeated pattern:
 *   const res = await apiFetch(url);
 *   if (!res.ok) { const body = await res.json().catch(...); throw ... }
 *   const data: T = await res.json();
 *
 * Usage:
 *   const data = await apiJson<ProjectListResponse>(`${API_BASE}/projects`);
 *   const project = await apiJson<Project>(url, { method: "POST", body: ... });
 */
export async function apiJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const res = await apiFetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw toApiError(res.status, body);
  }
  return res.json() as Promise<T>;
}

/**
 * Fire-and-forget mutation helper for endpoints that return no body (204)
 * or where the response body is irrelevant.
 *
 * Throws ApiError on non-2xx, returns void on success.
 */
export async function apiVoid(input: RequestInfo | URL, init?: RequestInit): Promise<void> {
  const res = await apiFetch(input, init);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw toApiError(res.status, body);
  }
}
