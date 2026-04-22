/**
 * VisualPlanEditor — scene-card editor for visual plans.
 *
 * Loads visual plan from GET /runs/{runId}/visual-plan, renders
 * editable scene cards keyed by scene_id, saves individual scenes
 * via PATCH /runs/{runId}/visual-plan/scenes/{sceneId}.
 * Per-scene regenerate and image-model override controls are present
 * but disabled until Phase 4 wiring.
 */

import { useState, useEffect, useCallback } from "react";
import { apiFetch } from "../../api/client";
import type { SceneData } from "../../types/api";

export type { SceneData } from "../../types/api";

export interface VisualPlanEditorProps {
  apiBase?: string;
  runId: number;
  onSuccess?: (data: Record<string, unknown>) => void;
  onError?: (action: "load" | "save", message: string) => void;
  readOnly?: boolean;
  pollIntervalMs?: number;
  suppressMissingPlanError?: boolean;
  pendingMessage?: string;
}

// --------------- styles ---------------

const CARD_STYLE: React.CSSProperties = {
  border: "1px solid #dee2e6",
  borderRadius: 6,
  padding: 12,
  marginBottom: 10,
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

const TAG_STYLE: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  fontSize: 11,
  backgroundColor: "#e9ecef",
  borderRadius: 10,
  marginRight: 4,
  marginBottom: 4,
};

const STATUS_COLORS: Record<string, string> = {
  pending: "#6c757d",
  generating: "#0d6efd",
  completed: "#198754",
  failed: "#dc3545",
};

const SMALL_BTN: React.CSSProperties = {
  padding: "4px 10px",
  fontSize: 12,
  border: "1px solid #ced4da",
  borderRadius: 3,
  backgroundColor: "#f8f9fa",
  cursor: "pointer",
};

// --------------- scene card ---------------

interface SceneCardProps {
  scene: SceneData;
  readOnly: boolean;
  saving: boolean;
  onPromptChange: (sceneId: string, value: string) => void;
  onMoodChange: (sceneId: string, value: string) => void;
  onCompositionChange: (sceneId: string, value: string) => void;
  onStyleTagsChange: (sceneId: string, value: string) => void;
  onSaveScene: (sceneId: string) => void;
  dirtyFields: Set<string>;
}

function SceneCard({
  scene,
  readOnly,
  saving,
  onPromptChange,
  onMoodChange,
  onCompositionChange,
  onStyleTagsChange,
  onSaveScene,
  dirtyFields,
}: SceneCardProps) {
  const fieldDisabled = readOnly || saving;
  const prefix = `scene-${scene.scene_id}`;
  const isDirty = dirtyFields.has(scene.scene_id);
  const statusColor = STATUS_COLORS[scene.generation_status] ?? "#6c757d";

  return (
    <div data-testid={prefix} style={CARD_STYLE}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#6c757d" }}>
          #{scene.scene_index + 1}
        </span>
        <span style={{ fontSize: 11, color: "#adb5bd" }}>{scene.scene_id}</span>
        <span
          data-testid={`${prefix}-status`}
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: statusColor,
            textTransform: "uppercase",
          }}
        >
          {scene.generation_status}
        </span>
        <span style={{ marginLeft: "auto" }} />
        {/* Regenerate — disabled until Phase 4 */}
        <button
          type="button"
          data-testid={`${prefix}-regenerate`}
          disabled
          style={{ ...SMALL_BTN, opacity: 0.4, cursor: "not-allowed" }}
          title="Regenerate image (Phase 4)"
        >
          🔄 Regenerate
        </button>
      </div>

      {/* Original text (read-only) */}
      <div style={{ marginBottom: 8 }}>
        <span style={FIELD_LABEL}>Original Text</span>
        <div
          data-testid={`${prefix}-original-text`}
          style={{
            padding: "6px 8px",
            fontSize: 13,
            backgroundColor: "#f8f9fa",
            borderRadius: 4,
            color: "#495057",
            whiteSpace: "pre-wrap",
          }}
        >
          {scene.original_text}
        </div>
      </div>

      {/* Prompt (editable) */}
      <div style={{ marginBottom: 8 }}>
        <label style={FIELD_LABEL} htmlFor={`${prefix}-prompt`}>
          Prompt
          {scene.prompt_source !== "auto_generated" && (
            <span style={{ fontWeight: 400, color: "#6c757d", marginLeft: 4 }}>
              ({scene.prompt_source})
            </span>
          )}
        </label>
        <textarea
          id={`${prefix}-prompt`}
          data-testid={`${prefix}-prompt`}
          style={TEXTAREA_STYLE}
          value={scene.prompt}
          readOnly={fieldDisabled}
          onChange={(e) => onPromptChange(scene.scene_id, e.target.value)}
        />
      </div>

      {/* Mood + Composition (side by side) */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-mood`}>Mood</label>
          <input
            id={`${prefix}-mood`}
            data-testid={`${prefix}-mood`}
            style={INPUT_STYLE}
            value={scene.mood ?? ""}
            readOnly={fieldDisabled}
            onChange={(e) => onMoodChange(scene.scene_id, e.target.value)}
          />
        </div>
        <div>
          <label style={FIELD_LABEL} htmlFor={`${prefix}-composition`}>Composition</label>
          <input
            id={`${prefix}-composition`}
            data-testid={`${prefix}-composition`}
            style={INPUT_STYLE}
            value={scene.composition ?? ""}
            readOnly={fieldDisabled}
            onChange={(e) => onCompositionChange(scene.scene_id, e.target.value)}
          />
        </div>
      </div>

      {/* Style tags */}
      <div style={{ marginBottom: 8 }}>
        <label style={FIELD_LABEL} htmlFor={`${prefix}-style-tags`}>
          Style Tags (comma-separated)
        </label>
        <input
          id={`${prefix}-style-tags`}
          data-testid={`${prefix}-style-tags`}
          style={INPUT_STYLE}
          value={scene.style_tags.join(", ")}
          readOnly={fieldDisabled}
          onChange={(e) => onStyleTagsChange(scene.scene_id, e.target.value)}
        />
        {scene.style_tags.length > 0 && (
          <div style={{ marginTop: 4 }}>
            {scene.style_tags.map((tag) => (
              <span key={tag} style={TAG_STYLE}>{tag}</span>
            ))}
          </div>
        )}
      </div>

      {/* Image model override — disabled until Phase 4 */}
      <div style={{ marginBottom: 8 }}>
        <span style={FIELD_LABEL}>Image Model Override</span>
        <select
          data-testid={`${prefix}-model-override`}
          disabled
          style={{ ...INPUT_STYLE, opacity: 0.5, cursor: "not-allowed" }}
          title="Image model override (Phase 4)"
        >
          <option value="">Default model</option>
        </select>
      </div>

      {/* Per-scene save button */}
      {!readOnly && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
          {isDirty && (
            <span data-testid={`${prefix}-dirty`} style={{ fontSize: 11, color: "#856404" }}>
              Unsaved changes
            </span>
          )}
          <span style={{ marginLeft: "auto" }} />
          <button
            type="button"
            data-testid={`${prefix}-save`}
            disabled={!isDirty || saving}
            onClick={() => onSaveScene(scene.scene_id)}
            style={{
              ...SMALL_BTN,
              backgroundColor: isDirty && !saving ? "#6c757d" : "#f8f9fa",
              color: isDirty && !saving ? "#fff" : "#6c757d",
              cursor: isDirty && !saving ? "pointer" : "not-allowed",
              opacity: isDirty && !saving ? 1 : 0.5,
            }}
          >
            {saving ? "Saving…" : "Save Scene"}
          </button>
        </div>
      )}
    </div>
  );
}

// --------------- main component ---------------

export default function VisualPlanEditor({
  apiBase = "/api/creator",
  runId,
  onSuccess,
  onError,
  readOnly = false,
  pollIntervalMs,
  suppressMissingPlanError = false,
  pendingMessage = "Waiting for generated scenes…",
}: VisualPlanEditorProps) {
  const [scenes, setScenes] = useState<SceneData[]>([]);
  const [savedScenes, setSavedScenes] = useState<Record<string, SceneData>>({});
  const [version, setVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set());
  const [pendingPlan, setPendingPlan] = useState(false);

  // Load plan
  const load = useCallback(
    async (showLoading: boolean) => {
      if (showLoading) setLoading(true);
      setError(null);
      try {
        const res = await apiFetch(`${apiBase}/runs/${runId}/visual-plan`);
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          const detail = body.detail ?? `Failed to load (${res.status})`;
          if (
            suppressMissingPlanError &&
            typeof detail === "string" &&
            detail.toLowerCase().includes("no visual plan")
          ) {
            setScenes([]);
            setSavedScenes({});
            setVersion(null);
            setDirtyFields(new Set());
            setPendingPlan(true);
            return;
          }
          throw new Error(detail);
        }
        const data = await res.json();
        const loaded = (data.scenes ?? []) as SceneData[];
        setScenes(loaded);
        const saved: Record<string, SceneData> = {};
        for (const s of loaded) {
          saved[s.scene_id] = { ...s };
        }
        setSavedScenes(saved);
        setVersion(data.version ?? null);
        setDirtyFields(new Set());
        setPendingPlan(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "Failed to load visual plan";
        setError(msg);
        onError?.("load", msg);
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [apiBase, runId, suppressMissingPlanError, onError],
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

  // Mark scene dirty
  const markDirty = useCallback((sceneId: string) => {
    setDirtyFields((prev) => {
      if (prev.has(sceneId)) return prev;
      const next = new Set(prev);
      next.add(sceneId);
      return next;
    });
  }, []);

  // Field handlers
  const handlePromptChange = useCallback((sceneId: string, value: string) => {
    setScenes((prev) =>
      prev.map((s) =>
        s.scene_id === sceneId
          ? { ...s, prompt: value, prompt_edited: true, prompt_source: "user_edited" as const }
          : s
      )
    );
    markDirty(sceneId);
  }, [markDirty]);

  const handleMoodChange = useCallback((sceneId: string, value: string) => {
    setScenes((prev) =>
      prev.map((s) => (s.scene_id === sceneId ? { ...s, mood: value || null } : s))
    );
    markDirty(sceneId);
  }, [markDirty]);

  const handleCompositionChange = useCallback((sceneId: string, value: string) => {
    setScenes((prev) =>
      prev.map((s) => (s.scene_id === sceneId ? { ...s, composition: value || null } : s))
    );
    markDirty(sceneId);
  }, [markDirty]);

  const handleStyleTagsChange = useCallback((sceneId: string, value: string) => {
    const tags = value.split(",").map((t) => t.trim()).filter(Boolean);
    setScenes((prev) =>
      prev.map((s) => (s.scene_id === sceneId ? { ...s, style_tags: tags } : s))
    );
    markDirty(sceneId);
  }, [markDirty]);

  // Save single scene via PATCH
  const handleSaveScene = useCallback(async (sceneId: string) => {
    const scene = scenes.find((s) => s.scene_id === sceneId);
    const saved = savedScenes[sceneId];
    if (!scene || !saved) return;

    // Build diff
    const updates: Record<string, unknown> = {};
    if (scene.prompt !== saved.prompt) updates.prompt = scene.prompt;
    if (scene.prompt_edited !== saved.prompt_edited) updates.prompt_edited = scene.prompt_edited;
    if (scene.prompt_source !== saved.prompt_source) updates.prompt_source = scene.prompt_source;
    if (JSON.stringify(scene.style_tags) !== JSON.stringify(saved.style_tags))
      updates.style_tags = scene.style_tags;
    if (scene.mood !== saved.mood) updates.mood = scene.mood;
    if (scene.composition !== saved.composition) updates.composition = scene.composition;

    if (Object.keys(updates).length === 0) return;

    if (version !== null) {
      updates.expected_version = version;
    }

    setSaving(true);
    setError(null);
    try {
      const res = await apiFetch(`${apiBase}/runs/${runId}/visual-plan/scenes/${sceneId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Save failed (${res.status})`);
      }
      const data = await res.json();
      const updatedScenes = (data.scenes ?? []) as SceneData[];

      setScenes(updatedScenes);
      const newSaved: Record<string, SceneData> = {};
      for (const s of updatedScenes) {
        newSaved[s.scene_id] = { ...s };
      }
      setSavedScenes(newSaved);
      setVersion(data.version ?? version);
      setDirtyFields((prev) => {
        const next = new Set(prev);
        next.delete(sceneId);
        return next;
      });
      onSuccess?.(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to save scene";
      setError(msg);
      onError?.("save", msg);
    } finally {
      setSaving(false);
    }
  }, [apiBase, runId, scenes, savedScenes, version, onSuccess, onError]);

  // --------------- render ---------------

  if (loading) {
    return (
      <div data-testid="visual-plan-editor" aria-busy="true">
        <p data-testid="visual-plan-loading">Loading visual plan…</p>
      </div>
    );
  }

  return (
    <div data-testid="visual-plan-editor">
      {error && (
        <div
          data-testid="visual-plan-error"
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

      {pendingPlan && !error && (
        <div
          data-testid="visual-plan-pending"
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

      {scenes.length === 0 ? (
        <p data-testid="visual-plan-empty" style={{ color: "#6c757d", fontSize: 13 }}>
          No scenes in visual plan. Generate a visual plan first.
        </p>
      ) : (
        <>
          <div data-testid="visual-plan-scenes">
            {scenes.map((scene) => (
              <SceneCard
                key={scene.scene_id}
                scene={scene}
                readOnly={readOnly}
                saving={saving}
                onPromptChange={handlePromptChange}
                onMoodChange={handleMoodChange}
                onCompositionChange={handleCompositionChange}
                onStyleTagsChange={handleStyleTagsChange}
                onSaveScene={handleSaveScene}
                dirtyFields={dirtyFields}
              />
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8 }}>
            {version !== null && (
              <span data-testid="visual-plan-version" style={{ fontSize: 11, color: "#6c757d" }}>
                v{version}
              </span>
            )}
            <span style={{ fontSize: 11, color: "#6c757d" }}>
              {scenes.length} scene{scenes.length !== 1 ? "s" : ""}
            </span>
          </div>
        </>
      )}
    </div>
  );
}
