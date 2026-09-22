import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import {
  createDemoRun, getDefaultWorkspaceId, getOnboarding, getProviderConfig,
  getWorkspaceDemoPlan, type DemoShortPlan, type OnboardingGuidance,
  type ProviderConfigView,
} from "../../api/demo";

type Disclosure = {
  readonly workspaceId: number;
  readonly plan: DemoShortPlan;
  readonly onboarding: OnboardingGuidance;
  readonly providers: ProviderConfigView;
};

export function DemoShortCard() {
  const navigate = useNavigate();
  const lock = useRef(false);
  const [busy, setBusy] = useState(false);
  const [disclosure, setDisclosure] = useState<Disclosure | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      if (disclosure) {
        if (!disclosure.plan.ready) return;
        const result = await createDemoRun(disclosure.workspaceId);
        navigate(`/projects/${result.seeded_project_id}`);
      } else {
        const workspaceId = await getDefaultWorkspaceId();
        const [plan, onboarding, providers] = await Promise.all([
          getWorkspaceDemoPlan(workspaceId), getOnboarding(workspaceId), getProviderConfig(),
        ]);
        setDisclosure({ workspaceId, plan, onboarding, providers });
      }
    } catch (err: unknown) {
      setError(err instanceof ApiError
        ? [err.detail, ...(err.recoverySteps ?? [])].join(" — ")
        : err instanceof Error ? err.message : "Could not start the demo Short.");
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  return (
    <div style={{ marginBottom: 24, padding: 16, background: "#f0f7ff", borderRadius: 8, border: "1px solid #cfe3ff", overflowWrap: "anywhere" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ flex: "1 1 240px", minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14 }}>New here? Try a sample Short</div>
          <div style={{ fontSize: 13, color: "#555" }}>
            Review the plan, then create a sample-backed timeline. Rendering requires your approval.
          </div>
        </div>
        <button type="button" data-testid="try-demo-button"
          disabled={busy || (disclosure !== null && !disclosure.plan.ready)} onClick={act}
          style={{ padding: "10px 20px", background: busy ? "#93b4f4" : "#4285f4", color: "#fff", border: "none", borderRadius: 6, fontSize: 14, fontWeight: 600, cursor: busy ? "not-allowed" : "pointer", whiteSpace: "nowrap" }}>
          {busy ? "Loading…" : disclosure ? "Create demo Short" : "Try the demo"}
        </button>
      </div>
      {disclosure && <div data-testid="demo-plan" style={{ marginTop: 12, fontSize: 13 }}>
        <p>Estimated cost: ${disclosure.plan.estimated_total_cost_usd.toFixed(2)}</p>
        <ul>{disclosure.plan.cost_line_items.map((item, i) => <li key={i}>
          {item.category}: {item.provider} / {item.model_key} — {item.quantity_label} (${item.estimated_cost_usd.toFixed(2)})
        </li>)}</ul>
        <p>Exposure: {disclosure.plan.external_exposure}</p>
        <p>Required approvals: {disclosure.plan.required_approvals.join(", ")}</p>
        <p>{disclosure.plan.next_action}</p>
        {disclosure.plan.blocking_reasons.map((reason) => <p key={reason} role="alert">{reason}</p>)}
        <p>For AI generation: {disclosure.onboarding.next_action}</p>
        <ol>{disclosure.onboarding.steps.map((step) => <li key={step}>{step}</li>)}</ol>
        <ul>{disclosure.providers.providers.map((provider) => <li key={provider.provider}>
          {provider.label}: {provider.status} — <span>{provider.hint}</span>
        </li>)}</ul>
      </div>}
      {error && <div data-testid="demo-error" role="alert"
        style={{ marginTop: 12, padding: "8px 12px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 4, color: "#b91c1c", fontSize: 13 }}>
        {error}
      </div>}
    </div>
  );
}
