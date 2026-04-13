/**
 * MarkdownScriptEditor — raw markdown editing with save and parse actions.
 *
 * Loads markdown content for a given run, lets the user edit it in a plain
 * textarea, then save via PUT or parse via POST.  Does NOT own fetch logic
 * for the *page*; it does own its own load/save/parse calls against the
 * run-scoped script endpoints.
 */

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../api/client";

// --------------- types ---------------

export interface MarkdownScriptEditorProps {
  /** Base URL for API calls (e.g. "/api/creator"). */
  apiBase?: string;
  /** Run ID whose script we're editing. */
  runId: number;
  /** Called when save or parse completes successfully. */
  onSuccess?: (action: "save" | "parse", data: Record<string, unknown>) => void;
  /** Called when an error occurs. */
  onError?: (action: "load" | "save" | "parse", message: string) => void;
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

export default function MarkdownScriptEditor({
  apiBase = "/api/creator",
  runId,
  onSuccess,
  onError,
  readOnly = false,
  pollIntervalMs,
  suppressMissingDraftError = false,
  pendingMessage = "Waiting for generated script…",
}: MarkdownScriptEditorProps) {
  const [markdown, setMarkdown] = useState("");
  const [savedMarkdown, setSavedMarkdown] = useState("");
  const [version, setVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDraft, setPendingDraft] = useState(false);

  const isDirty = markdown !== savedMarkdown;

  // Load markdown on mount / runId change
  const load = useCallback(
    async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await apiFetch(`${apiBase}/runs/${runId}/script/markdown`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body.detail ?? `Failed to load (${res.status})`;
          if (
            suppressMissingDraftError &&
            typeof detail === "string" &&
            detail.toLowerCase().includes("no script draft")
          ) {
            setMarkdown("");
            setSavedMarkdown("");
            setVersion(null);
            setPendingDraft(true);
            return;
          }
          throw new Error(detail);
        }
        const data = await res.json();
        setMarkdown(data.markdown ?? "");
        setSavedMarkdown(data.markdown ?? "");
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

  // Save markdown
  const handleSave = useCallback(async () => {
    if (!isDirty || saving || !markdown.trim()) return;

    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase}/runs/${runId}/script/markdown`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ markdown }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Save failed (${res.status})`);
      }
      const data = await res.json();
      const draft = (data.draft ?? {}) as Record<string, unknown>;
      setSavedMarkdown(markdown);
      const newVersion = (draft.version as number) ?? version;
      setVersion(newVersion);
      onSuccess?.("save", data);

      // Auto-parse after successful save to sync structured data
      try {
        const parseRes = await apiFetch(`${apiBase}/runs/${runId}/script/parse-markdown`, {
          method: "POST",
        });
        if (parseRes.ok) {
          const parseData = await parseRes.json();
          setVersion(parseData.version ?? newVersion);
          onSuccess?.("parse", parseData);
        }
      } catch {
        // parse failure is non-critical — structured data just stays stale
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setError(msg);
      onError?.("save", msg);
    } finally {
      setSaving(false);
    }
  }, [apiBase, runId, markdown, isDirty, saving, version, onSuccess, onError]);

  // Parse markdown → structured sections
  const handleParse = useCallback(async () => {
    if (parsing) return;

    setParsing(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase}/runs/${runId}/script/parse-markdown`, {
        method: "POST",
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Parse failed (${res.status})`);
      }
      const data = await res.json();
      setVersion(data.version ?? version);
      onSuccess?.("parse", data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to parse";
      setError(msg);
      onError?.("parse", msg);
    } finally {
      setParsing(false);
    }
  }, [apiBase, runId, parsing, version, onSuccess, onError]);

  // --------------- render ---------------

  if (loading) {
    return (
      <div data-testid="markdown-editor" aria-busy="true">
        <p data-testid="markdown-loading">Loading script…</p>
      </div>
    );
  }

  return (
    <div data-testid="markdown-editor">
      {error && (
        <div
          data-testid="markdown-error"
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
          data-testid="markdown-pending"
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
        htmlFor={`markdown-textarea-${runId}`}
        style={{ display: "block", fontWeight: 600, fontSize: 13, marginBottom: 4 }}
      >
        Markdown Script
      </label>
      <textarea
        id={`markdown-textarea-${runId}`}
        data-testid="markdown-textarea"
        value={markdown}
        onChange={(e) => setMarkdown(e.target.value)}
        readOnly={readOnly}
        disabled={saving || parsing}
        style={{
          width: "100%",
          minHeight: 300,
          fontFamily: "monospace",
          fontSize: 13,
          padding: 8,
          border: "1px solid #ced4da",
          borderRadius: 4,
          resize: "vertical",
          boxSizing: "border-box",
        }}
      />

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 8,
        }}
      >
        {version !== null && (
          <span data-testid="markdown-version" style={{ fontSize: 11, color: "#6c757d" }}>
            v{version}
          </span>
        )}
        {isDirty && (
          <span data-testid="markdown-dirty" style={{ fontSize: 11, color: "#856404" }}>
            Unsaved changes
          </span>
        )}
        <span style={{ marginLeft: "auto" }} />
        {!readOnly && (
          <>
            <button
              type="button"
              data-testid="markdown-save-btn"
              disabled={!isDirty || saving || !markdown.trim()}
              onClick={handleSave}
              aria-busy={saving}
              style={{
                padding: "6px 16px",
                fontSize: 13,
                borderRadius: 4,
                border: "1px solid #6c757d",
                backgroundColor: "#6c757d",
                color: "#fff",
                cursor: isDirty && !saving ? "pointer" : "not-allowed",
                opacity: isDirty && !saving ? 1 : 0.5,
              }}
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              data-testid="markdown-parse-btn"
              disabled={parsing || isDirty}
              onClick={handleParse}
              aria-busy={parsing}
              style={{
                padding: "6px 16px",
                fontSize: 13,
                borderRadius: 4,
                border: "1px solid #007bff",
                backgroundColor: "#007bff",
                color: "#fff",
                cursor: !parsing && !isDirty ? "pointer" : "not-allowed",
                opacity: !parsing && !isDirty ? 1 : 0.5,
              }}
            >
              {parsing ? "Parsing…" : "Parse to Sections"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
