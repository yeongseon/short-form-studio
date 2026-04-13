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
