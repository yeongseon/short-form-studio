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
 * Exposes the HTTP status and parsed detail message for structured error handling.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
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
    const detail = (body?.detail as string) ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
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
    const detail = (body?.detail as string) ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }
}
