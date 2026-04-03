/**
 * StructuredScriptEditor — section-card editor for structured scripts.
 *
 * Loads structured sections from GET /runs/{runId}/script/structured,
 * renders editable cards, supports reorder via up/down, and saves via
 * PUT /runs/{runId}/script/structured.  Section IDs are opaque — the
 * backend owns ID preservation.
 */

import { useState, useEffect, useCallback } from "react";

// --------------- types ---------------

export interface VisualOverrideData {
  type: "prompt" | "image_url" | "none";
  value?: string | null;
}

export interface SectionData {
  section_id: string;
  type: string;
  text: string;
  display_text?: string | null;
  speaker?: string | null;
  duration?: number | null;
  turn_kind?: string | null;
  visual_override?: VisualOverrideData | null;
}

export interface StructuredScriptEditorProps {
  apiBase?: string;
  runId: number;
  onSuccess?: (data: Record<string, unknown>) => void;
  onError?: (action: "load" | "save", message: string) => void;
  readOnly?: boolean;
  pollIntervalMs?: number;
  suppressMissingDraftError?: boolean;
  pendingMessage?: string;
}

// --------------- helpers ---------------

function deepEqual(a: SectionData[], b: SectionData[]): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function swap<T>(arr: T[], i: number, j: number): T[] {
  const copy = [...arr];
  [copy[i], copy[j]] = [copy[j], copy[i]];
  return copy;
}

// --------------- styles ---------------

const CARD_STYLE: React.CSSProperties = {
  border: "1px solid #dee2e6",
  borderRadius: 6,
  padding: 12,
  marginBottom: 8,
  backgroundColor: "#fff",
};

const FIELD_LABEL: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 600,
  color: "#495057",
  marginBottom: 2,
};

const INPUT_STYLE: React.CSSProperties = {
  width: "100%",
  padding: "4px 8px",
  fontSize: 13,
  border: "1px solid #ced4da",
  borderRadius: 4,
  boxSizing: "border-box",
};

const TEXTAREA_STYLE: React.CSSProperties = {
  ...INPUT_STYLE,
  minHeight: 60,
  resize: "vertical",
  fontFamily: "inherit",
};

const SMALL_BTN: React.CSSProperties = {
  padding: "2px 8px",
  fontSize: 12,
  border: "1px solid #ced4da",
  borderRadius: 3,
  backgroundColor: "#f8f9fa",
  cursor: "pointer",
};

// --------------- section card ---------------

interface SectionCardProps {
  section: SectionData;
  index: number;
  total: number;
  readOnly: boolean;
  disabled: boolean;
  onChange: (index: number, field: keyof SectionData, value: string | number | null) => void;
  onMoveUp: (index: number) => void;
  onMoveDown: (index: number) => void;
}

function SectionCard({
  section,
  index,
  total,
  readOnly,
  disabled,
  onChange,
  onMoveUp,
  onMoveDown,
}: SectionCardProps) {
  const fieldDisabled = readOnly || disabled;
  const prefix = `section-${index}`;

  return (
    <div data-testid={`section-card-${index}`} style={CARD_STYLE}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#6c757d" }}>
          #{index + 1}
        </span>
        <span style={{ fontSize: 11, color: "#adb5bd" }}>{section.section_id}</span>
        <span style={{ marginLeft: "auto" }} />
        {!readOnly && (
          <>
            <button
              type="button"
              data-testid={`${prefix}-move-up`}
              disabled={index === 0 || disabled}
              onClick={() => onMoveUp(index)}
              style={SMALL_BTN}
              aria-label={`Move section ${index + 1} up`}
            >
              ↑
            </button>
            <button
              type="button"
              data-testid={`${prefix}-move-down`}
              disabled={index === total - 1 || disabled}
              onClick={() => onMoveDown(index)}
              style={SMALL_BTN}
              aria-label={`Move section ${index + 1} down`}
            >
              ↓
            </button>
          </>
        )}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-type`}>Type</label>
          <input
            id={`${prefix}-type`}
            data-testid={`${prefix}-type`}
            style={INPUT_STYLE}
            value={section.type}
            readOnly={fieldDisabled}
            onChange={(e) => onChange(index, "type", e.target.value)}
          />
        </div>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-speaker`}>Speaker</label>
          <input
            id={`${prefix}-speaker`}
            data-testid={`${prefix}-speaker`}
            style={INPUT_STYLE}
            value={section.speaker ?? ""}
            readOnly={fieldDisabled}
            onChange={(e) => onChange(index, "speaker", e.target.value || null)}
          />
        </div>
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={FIELD_LABEL} htmlFor={`${prefix}-text`}>Text</label>
        <textarea
          id={`${prefix}-text`}
          data-testid={`${prefix}-text`}
          style={TEXTAREA_STYLE}
          value={section.text}
          readOnly={fieldDisabled}
          onChange={(e) => onChange(index, "text", e.target.value)}
        />
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={FIELD_LABEL} htmlFor={`${prefix}-display-text`}>Display Text</label>
        <input
          id={`${prefix}-display-text`}
          data-testid={`${prefix}-display-text`}
          style={INPUT_STYLE}
          value={section.display_text ?? ""}
          readOnly={fieldDisabled}
          onChange={(e) => onChange(index, "display_text", e.target.value || null)}
        />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-duration`}>Duration (s)</label>
          <input
            id={`${prefix}-duration`}
            data-testid={`${prefix}-duration`}
            type="number"
            step="0.1"
            min="0"
            style={INPUT_STYLE}
            value={section.duration ?? ""}
            readOnly={fieldDisabled}
            onChange={(e) =>
              onChange(index, "duration", e.target.value ? parseFloat(e.target.value) : null)
            }
          />
        </div>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-visual-override`}>Visual Override</label>
          <input
            id={`${prefix}-visual-override`}
            data-testid={`${prefix}-visual-override`}
            style={INPUT_STYLE}
            placeholder="prompt text or image URL"
            value={section.visual_override?.value ?? ""}
            readOnly={fieldDisabled}
            onChange={(e) => {
              // Simplified: treat any non-empty value as a "prompt" visual override
              onChange(index, "visual_override" as keyof SectionData, e.target.value || null);
            }}
          />
        </div>
      </div>
    </div>
  );
}

// --------------- main component ---------------

export default function StructuredScriptEditor({
  apiBase = "/api/creator",
  runId,
  onSuccess,
  onError,
  readOnly = false,
  pollIntervalMs,
  suppressMissingDraftError = false,
  pendingMessage = "Waiting for generated sections…",
}: StructuredScriptEditorProps) {
  const [sections, setSections] = useState<SectionData[]>([]);
  const [savedSections, setSavedSections] = useState<SectionData[]>([]);
  const [version, setVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingDraft, setPendingDraft] = useState(false);

  const isDirty = !deepEqual(sections, savedSections);

  // Load sections
  const load = useCallback(
    async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase}/runs/${runId}/script/structured`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body.detail ?? `Failed to load (${res.status})`;
          if (
            suppressMissingDraftError &&
            typeof detail === "string" &&
            detail.toLowerCase().includes("no script draft")
          ) {
            setSections([]);
            setSavedSections([]);
            setVersion(null);
            setPendingDraft(true);
            return;
          }
          throw new Error(detail);
        }
        const data = await res.json();
        const loaded = (data.sections ?? []) as SectionData[];
        setSections(loaded);
        setSavedSections(loaded);
        setVersion(data.version ?? null);
        setPendingDraft(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load sections";
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
    return () => { cancelled = true; };
  }, [load]);

  useEffect(() => {
    if (!pollIntervalMs) return;
    const timer = setInterval(() => {
      void load(false);
    }, pollIntervalMs);
    return () => clearInterval(timer);
  }, [pollIntervalMs, load]);

  // Field change
  const handleChange = useCallback(
    (index: number, field: keyof SectionData, value: string | number | null) => {
      setSections((prev) => {
        const next = [...prev];
        const section = { ...next[index] };

        if (field === "visual_override") {
          section.visual_override = value
            ? { type: "prompt", value: value as string }
            : null;
        } else {
          (section as Record<string, unknown>)[field] = value;
        }

        next[index] = section;
        return next;
      });
    },
    [],
  );

  // Reorder
  const handleMoveUp = useCallback((index: number) => {
    if (index <= 0) return;
    setSections((prev) => swap(prev, index, index - 1));
  }, []);

  const handleMoveDown = useCallback((index: number) => {
    setSections((prev) => {
      if (index >= prev.length - 1) return prev;
      return swap(prev, index, index + 1);
    });
  }, []);

  // Save
  const handleSave = useCallback(async () => {
    if (!isDirty || saving) return;

    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/runs/${runId}/script/structured`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sections }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Save failed (${res.status})`);
      }
      const data = await res.json();
      const draft = (data.draft ?? {}) as Record<string, unknown>;
      setSavedSections(sections);
      setVersion((draft.version as number) ?? version);
      onSuccess?.(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save";
      setError(msg);
      onError?.("save", msg);
    } finally {
      setSaving(false);
    }
  }, [apiBase, runId, sections, isDirty, saving, version, onSuccess, onError]);

  // --------------- render ---------------

  if (loading) {
    return (
      <div data-testid="structured-editor" aria-busy="true">
        <p data-testid="structured-loading">Loading sections…</p>
      </div>
    );
  }

  return (
    <div data-testid="structured-editor">
      {error && (
        <div
          data-testid="structured-error"
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
          data-testid="structured-pending"
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

      {sections.length === 0 ? (
        <p data-testid="structured-empty" style={{ color: "#6c757d", fontSize: 13 }}>
          No sections yet. Use the JSON editor to define scenes, then save to generate sections.
        </p>
      ) : (
        <div data-testid="structured-sections">
          {sections.map((section, idx) => (
            <SectionCard
              key={section.section_id}
              section={section}
              index={idx}
              total={sections.length}
              readOnly={readOnly}
              disabled={saving}
              onChange={handleChange}
              onMoveUp={handleMoveUp}
              onMoveDown={handleMoveDown}
            />
          ))}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
        {version !== null && (
          <span data-testid="structured-version" style={{ fontSize: 11, color: "#6c757d" }}>
            v{version}
          </span>
        )}
        {isDirty && (
          <span data-testid="structured-dirty" style={{ fontSize: 11, color: "#856404" }}>
            Unsaved changes
          </span>
        )}
        <span style={{ marginLeft: "auto" }} />
        {!readOnly && sections.length > 0 && (
          <button
            type="button"
            data-testid="structured-save-btn"
            disabled={!isDirty || saving}
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
            {saving ? "Saving…" : "Save Sections"}
          </button>
        )}
      </div>
    </div>
  );
}
