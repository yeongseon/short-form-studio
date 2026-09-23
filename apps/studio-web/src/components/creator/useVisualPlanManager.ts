import { useState, useLayoutEffect, useEffect, useCallback, useMemo, useRef } from "react";
import { apiJson, ApiError, API_BASE } from "../../api/client";
import type { VisualScene } from "../../types/api";

export type { VisualScene } from "../../types/api";

const VISUAL_PLAN_FLOW_STAGES = new Set([
  "VISUAL_PLAN_SETUP", "VISUAL_PLAN_GENERATING", "VISUAL_PLAN_REVIEW",
  "VISUAL_ASSET_GENERATING", "VISUAL_ASSET_REVIEW", "AUDIO_GENERATING",
  "SUBTITLE_GENERATING", "RENDER_GENERATING", "FINAL_REVIEW", "PUBLISHED",
]);

type EditableFields = Pick<VisualScene,
  "prompt" | "prompt_edited" | "prompt_source" | "mood" | "composition" | "style_tags">;
type Draft = Partial<EditableFields>;
type Plan = { readonly scenes?: VisualScene[]; readonly version?: number };
type PlanState = {
  readonly scenes: Record<string, VisualScene>;
  readonly drafts: Record<string, Draft>;
  readonly version: number | null;
  readonly error: string | null;
  readonly loadError: string | null;
};

const EMPTY: PlanState = { scenes: {}, drafts: {}, version: null, error: null, loadError: null };
const EDITABLE_KEYS = ["prompt", "prompt_edited", "prompt_source", "mood", "composition", "style_tags"] as const;

function mergePlan(state: PlanState, data: Plan): PlanState {
  if (state.version !== null && data.version !== undefined && data.version < state.version) return state;
  const scenes = Object.fromEntries((data.scenes ?? []).map((scene) => [scene.scene_id, scene]));
  // Retain removed dirty scenes until their owner resets; a poll is not consent to discard.
  for (const id of Object.keys(state.drafts)) {
    if (!scenes[id] && state.scenes[id]) scenes[id] = state.scenes[id];
  }
  return { ...state, scenes, version: data.version ?? state.version };
}

export function useVisualPlanManager(
  runId: number,
  currentStage: string,
  onStatusMessage?: (msg: string | null) => void,
) {
  const enabled = VISUAL_PLAN_FLOW_STAGES.has(currentStage);
  const owner = useMemo(() => ({ runId, enabled }), [runId, enabled]);
  const activeOwner = useRef<typeof owner | null>(owner);
  const latest = useRef<PlanState>(EMPTY);
  const [state, setState] = useState<PlanState>(EMPTY);
  const [saving, setSaving] = useState<ReadonlySet<string>>(new Set());
  const pendingSaves = useRef(new Set<string>());
  const readSequence = useRef(0);
  const update = useCallback((apply: (previous: PlanState) => PlanState) => {
    latest.current = apply(latest.current);
    setState(latest.current);
  }, []);

  useLayoutEffect(() => {
    activeOwner.current = owner;
    update(() => EMPTY);
    pendingSaves.current = new Set();
    setSaving(new Set());
    return () => { activeOwner.current = null; };
  }, [owner, update]);

  const refreshVisualPlan = useCallback(async () => {
    if (!owner.enabled || activeOwner.current !== owner) return;
    const sequence = ++readSequence.current;
    const ownsResponse = () => activeOwner.current === owner && sequence === readSequence.current;
    try {
      const data = await apiJson<Plan>(`${API_BASE}/runs/${runId}/visual-plan`);
      if (ownsResponse()) update((previous) => mergePlan({ ...previous, loadError: null }, data));
    } catch (err) {
      if (!ownsResponse()) return;
      if (err instanceof ApiError && err.detail.toLowerCase().includes("no visual plan")) {
        update((previous) => Object.keys(previous.drafts).length ? previous : EMPTY);
        return;
      }
      update((previous) => ({ ...previous, loadError: err instanceof Error ? err.message : "Failed to load visual plan" }));
    }
  }, [owner, runId, update]);

  useEffect(() => { void refreshVisualPlan(); }, [refreshVisualPlan, currentStage]);

  const onFieldChange = useCallback((sceneId: string, field: "prompt" | "mood" | "composition" | "style_tags", value: string) => {
    if (activeOwner.current !== owner) return;
    update((previous) => {
      if (!previous.scenes[sceneId]) return previous;
      const draft = { ...previous.drafts[sceneId] };
      switch (field) {
        case "prompt":
          draft.prompt = value;
          draft.prompt_edited = true;
          draft.prompt_source = "user_edited";
          break;
        case "mood": draft.mood = value.trim() ? value : null; break;
        case "composition": draft.composition = value.trim() ? value : null; break;
        case "style_tags": draft.style_tags = value.split(",").map((item) => item.trim()).filter(Boolean); break;
        default: { const unreachable: never = field; return unreachable; }
      }
      return { ...previous, drafts: { ...previous.drafts, [sceneId]: draft } };
    });
  }, [owner, update]);

  const onSaveScene = useCallback(async (sceneId: string) => {
    if (activeOwner.current !== owner || pendingSaves.current.has(sceneId)) return;
    const snapshot = latest.current;
    const submitted = snapshot.drafts[sceneId];
    if (!submitted || !snapshot.scenes[sceneId]) return;
    pendingSaves.current.add(sceneId);
    setSaving(new Set(pendingSaves.current));
    update((previous) => ({ ...previous, error: null }));
    try {
      const data = await apiJson<Plan>(`${API_BASE}/runs/${runId}/visual-plan/scenes/${sceneId}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...submitted, ...(snapshot.version === null ? {} : { expected_version: snapshot.version }) }),
      });
      if (activeOwner.current !== owner) return;
      update((previous) => {
        const acknowledged = data.scenes?.find((scene) => scene.scene_id === sceneId);
        const draft = { ...previous.drafts[sceneId] };
        for (const key of EDITABLE_KEYS) {
          if (key in submitted && JSON.stringify(draft[key]) === JSON.stringify(submitted[key]) &&
              JSON.stringify(acknowledged?.[key]) === JSON.stringify(submitted[key])) delete draft[key];
        }
        const drafts = { ...previous.drafts };
        if (Object.keys(draft).length) drafts[sceneId] = draft;
        else delete drafts[sceneId];
        return mergePlan({ ...previous, drafts }, data);
      });
      onStatusMessage?.(`Saved visual details for ${sceneId}`);
    } catch (err) {
      if (activeOwner.current !== owner) return;
      const message = err instanceof Error ? err.message : "Failed to save visual details";
      update((previous) => ({ ...previous, error: message }));
      onStatusMessage?.(message);
    } finally {
      if (activeOwner.current === owner) {
        pendingSaves.current.delete(sceneId);
        setSaving(new Set(pendingSaves.current));
      }
    }
  }, [owner, runId, onStatusMessage, update]);

  const visualFieldBySceneId = useMemo(() => Object.fromEntries(
    Object.entries(state.scenes).map(([id, scene]) => [id, {
      ...scene, ...state.drafts[id], dirty: Boolean(state.drafts[id]), saving: saving.has(id),
    }]),
  ), [state.scenes, state.drafts, saving]);

  return { visualFieldBySceneId, onFieldChange, onSaveScene, refreshVisualPlan,
    visualError: state.error ?? state.loadError, visualVersion: state.version };
}
