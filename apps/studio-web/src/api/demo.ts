/**
 * P0-4: typed client wrappers for the first-run surfaces (onboarding, provider
 * config, demo Short plan + seed). These make the SF-73/76/77 + P0-3 backend
 * routes consumable from the UI. The backend derives the workspace from auth for
 * resource access, but these routes are path-scoped, so callers pass the id.
 */
import { apiJson, API_BASE } from "./client";

export interface OnboardingGuidance {
  is_first_run: boolean;
  flow: "first_run" | "returning";
  steps: string[];
  duration_preset_ids: string[];
  style_template_ids: string[];
  review_gates: string[];
  custom_duration_hint_seconds: number;
  next_action: string;
}

export interface ProviderConfigState {
  provider: string;
  label: string;
  env_var: string | null;
  configured: boolean;
  is_local: boolean;
  requires_gpu: boolean;
  status: string;
  categories: string[];
  unavailable_categories: string[];
  hint: string;
}

export interface ProviderConfigView {
  providers: ProviderConfigState[];
}

export interface DemoShortPlan {
  ready: boolean;
  blocking_reasons: string[];
  required_approvals: string[];
  cost_line_items: {
    category: string;
    provider: string;
    model_key: string;
    estimated_cost_usd: number;
    quantity_label: string;
  }[];
  estimated_total_cost_usd: number;
  external_exposure: string;
  next_action: string;
}

export interface DemoRunResult {
  run: Record<string, unknown>;
  seeded_project_id: number;
  timeline_id: string;
  plan: DemoShortPlan;
}

export function getOnboarding(workspaceId: number): Promise<OnboardingGuidance> {
  return apiJson<OnboardingGuidance>(`${API_BASE}/workspaces/${workspaceId}/onboarding`);
}

export function getProviderConfig(): Promise<ProviderConfigView> {
  return apiJson<ProviderConfigView>(`${API_BASE}/models/provider-config`);
}

export function getDemoPlan(projectId: number): Promise<DemoShortPlan> {
  return apiJson<DemoShortPlan>(`${API_BASE}/projects/${projectId}/demo-short/plan`);
}

export function createDemoRun(workspaceId: number): Promise<DemoRunResult> {
  return apiJson<DemoRunResult>(`${API_BASE}/workspaces/${workspaceId}/demo-short/runs`, {
    method: "POST",
  });
}

interface WorkspaceListResponse {
  workspaces: { id: number; name?: string }[];
}

/** Resolve the caller's default (first) workspace id from auth-scoped membership. */
export async function getDefaultWorkspaceId(): Promise<number> {
  const data = await apiJson<WorkspaceListResponse>(`${API_BASE}/workspaces`);
  const first = data.workspaces[0];
  if (first === undefined) {
    throw new Error("No workspace available for the current user");
  }
  return first.id;
}

/** One-call demo path: resolve the workspace, then seed a sample-backed run. */
export async function startDemoShort(): Promise<DemoRunResult> {
  const workspaceId = await getDefaultWorkspaceId();
  return createDemoRun(workspaceId);
}
