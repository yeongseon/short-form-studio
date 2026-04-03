/**
 * JsonScriptEditor — JSON-based script editing with save action.
 *
 * Loads JSON script for a given run, lets the user edit in a textarea,
 * then save via PUT.  On save the backend parses JSON into structured
 * sections automatically — no separate parse step needed.
 */

import { useState, useEffect, useCallback } from "react";

// --------------- types ---------------

export interface JsonScriptEditorProps {
  /** Base URL for API calls (e.g. "/api/creator"). */
  apiBase?: string;
  /** Run ID whose script we're editing. */
  runId: number;
  /** Called when save completes successfully. */
  onSuccess?: (action: "save", data: Record<string, unknown>) => void;
  /** Called when an error occurs. */
  onError?: (action: "load" | "save", message: string) => void;
  /** Whether the editor should be read-only. */
  readOnly?: boolean;
  /** Optional polling interval for reloading content while generation is in progress. */
  pollIntervalMs?: number;
  /** Treat missing draft as a waiting state instead of an error. */
  suppressMissingDraftError?: boolean;
  /** Message shown when the draft is not available yet. */
  pendingMessage?: string;
}

// --------------- component ---------------

export default function JsonScriptEditor({
  apiBase = "/api/creator",
  runId,
  onSuccess,
  onError,
  readOnly = false,
  pollIntervalMs,
  suppressMissingDraftError = false,
  pendingMessage = "Waiting for script…",
}: JsonScriptEditorProps) {
  const [jsonText, setJsonText] = useState("");
  const [savedJson, setSavedJson] = useState("");
  const [version, setVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [pendingDraft, setPendingDraft] = useState(false);

  const isDirty = jsonText !== savedJson;

  // Validate JSON on change
  useEffect(() => {
    if (!jsonText.trim()) {
      setParseError(null);
      return;
    }
    try {
      JSON.parse(jsonText);
      setParseError(null);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Invalid JSON");
    }
  }, [jsonText]);

  // Load JSON on mount / runId change
  const load = useCallback(
    async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase}/runs/${runId}/script/json`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body.detail ?? `Failed to load (${res.status})`;
          if (
            suppressMissingDraftError &&
            typeof detail === "string" &&
            detail.toLowerCase().includes("no script draft")
          ) {
            setJsonText("");
            setSavedJson("");
            setVersion(null);
            setPendingDraft(true);
            return;
          }
          throw new Error(detail);
        }
        const data = await res.json();
        setJsonText(data.json_script ?? "");
        setSavedJson(data.json_script ?? "");
        setVersion(data.version ?? null);
        setPendingDraft(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load script";
        setError(msg);
        onError?.("load", msg);
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [apiBase, runId, suppressMissingDraftError, onError],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await load(true);
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  useEffect(() => {
    if (!pollIntervalMs) return;
    const timer = setInterval(() => {
      void load(false);
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [pollIntervalMs, load]);

  // Save JSON
  const handleSave = useCallback(async () => {
    if (!isDirty || saving || !jsonText.trim() || parseError) return;

    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/runs/${runId}/script/json`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ json_script: jsonText }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Save failed (${res.status})`);
      }
      const data = await res.json();
      const draft = (data.draft ?? {}) as Record<string, unknown>;
      setSavedJson(jsonText);
      setVersion((draft.version as number) ?? version);
      onSuccess?.("save", data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setError(msg);
      onError?.("save", msg);
    } finally {
      setSaving(false);
    }
  }, [apiBase, runId, jsonText, isDirty, saving, parseError, version, onSuccess, onError]);

  // --------------- render ---------------

  if (loading) {
    return (
      <div data-testid="json-editor" aria-busy="true">
        <p data-testid="json-loading">Loading script…</p>
      </div>
    );
  }

  return (
    <div data-testid="json-editor">
      {error && (
        <div
          data-testid="json-error"
          role="alert"
          style={{
            padding: "8px 12px",
            marginBottom: 12,
            backgroundColor: "#f8d7da",
            color: "#721c24",
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {pendingDraft && !error && (
        <div
          data-testid="json-pending"
          style={{
            padding: "8px 12px",
            marginBottom: 12,
            backgroundColor: "#eff6ff",
            color: "#1e40af",
            borderRadius: 4,
            fontSize: 13,
          }}
        >
          {pendingMessage}
        </div>
      )}

      <label
        htmlFor={`json-textarea-${runId}`}
        style={{ display: "block", fontWeight: 600, fontSize: 13, marginBottom: 4 }}
      >
        JSON Script
      </label>
      <textarea
        id={`json-textarea-${runId}`}
        data-testid="json-textarea"
        value={jsonText}
        onChange={(e) => setJsonText(e.target.value)}
        readOnly={readOnly}
        disabled={saving}
        style={{
          width: "100%",
          minHeight: 300,
          fontFamily: "monospace",
          fontSize: 13,
          padding: 8,
          border: `1px solid ${parseError ? "#dc2626" : "#ced4da"}`,
          borderRadius: 4,
          resize: "vertical",
          boxSizing: "border-box",
        }}
      />

      {parseError && (
        <div
          data-testid="json-parse-error"
          style={{ fontSize: 12, color: "#dc2626", marginTop: 4 }}
        >
          JSON Error: {parseError}
        </div>
      )}

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 8,
        }}
      >
        {version !== null && (
          <span data-testid="json-version" style={{ fontSize: 11, color: "#6c757d" }}>
            v{version}
          </span>
        )}
        {isDirty && (
          <span data-testid="json-dirty" style={{ fontSize: 11, color: "#856404" }}>
            Unsaved changes
          </span>
        )}
        <span style={{ marginLeft: "auto" }} />
        {!readOnly && (
          <button
            type="button"
            data-testid="json-save-btn"
            disabled={!isDirty || saving || !jsonText.trim() || !!parseError}
            onClick={handleSave}
            aria-busy={saving}
            style={{
              padding: "6px 16px",
              fontSize: 13,
              borderRadius: 4,
              border: "1px solid #6c757d",
              backgroundColor: "#6c757d",
              color: "#fff",
              cursor: isDirty && !saving && !parseError ? "pointer" : "not-allowed",
              opacity: isDirty && !saving && !parseError ? 1 : 0.5,
            }}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        )}
      </div>
    </div>
  );
}
