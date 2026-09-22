import { useEffect, useState } from "react";
import { ApiError } from "../api/client";
import { getProviderConfig, type ProviderConfigState, type ProviderConfigStatus } from "../api/demo";
import Button from "../components/ui/Button";

const STATUS_LABELS: Readonly<Record<ProviderConfigStatus, string>> = {
  not_configured: "Not configured",
  configured_unverified: "Configured — unverified",
  configured_available: "Available",
  configured_unavailable: "Unavailable",
  unknown: "Unknown",
};

export default function SettingsPage() {
  const [providers, setProviders] = useState<readonly ProviderConfigState[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    getProviderConfig().then(
      (view) => {
        if (!active) return;
        setProviders(view.providers);
        setLoading(false);
      },
      (reason: unknown) => {
        if (!active) return;
        const status = reason instanceof ApiError ? ` (${reason.status})` : "";
        setError(`Unable to load provider status${status}. Check server access and retry.`);
        setLoading(false);
      },
    );
    return () => { active = false; };
  }, [revision]);

  function refresh() {
    setLoading(true);
    setError(null);
    setProviders([]);
    setRevision((value) => value + 1);
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 8px" }}>Settings</h1>
      <p style={{ margin: "0 0 16px", color: "#6b7280", fontSize: 14 }}>
        View provider configuration and availability for model-backed generation.
        Configured credentials are not proof of availability or key validity.
      </p>
      <p style={{ margin: "0 0 24px", color: "#6b7280", fontSize: 14 }}>
        Read-only: ask your deployment operator to set the named environment variables
        through the server environment or secret manager, then reload the affected services
        and refresh here. Keys are never entered or stored in this browser.
        Refresh reads the latest server status; remote credentials may remain unverified.
      </p>

      <section aria-labelledby="provider-settings-heading" style={{ border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #e5e7eb", display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <h2 id="provider-settings-heading" style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>Providers &amp; API Keys</h2>
          <Button variant="ghost" disabled={loading} onClick={refresh}>
            {error ? "Retry provider status" : "Refresh provider status"}
          </Button>
        </div>

        {loading && <div role="status" style={{ padding: 20, fontSize: 14, color: "#6b7280" }}>Loading provider status...</div>}
        {!loading && !error && providers.length === 0 && (
          <p style={{ padding: 20, margin: 0, fontSize: 14 }}>No providers reported by the server.</p>
        )}
        {!loading && !error && providers.map((entry, index) => (
          <div key={entry.provider} style={{ padding: 20, overflowWrap: "anywhere", borderBottom: index < providers.length - 1 ? "1px solid #f3f4f6" : "none" }}>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
              <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#111827" }}>{entry.label}</h3>
              <span style={{
                display: "inline-flex", padding: "2px 8px", borderRadius: 999,
                background: entry.status === "configured_available" ? "#dcfce7" : "#f3f4f6",
                color: entry.status === "configured_available" ? "#166534" : "#4b5563",
                fontSize: 12, fontWeight: 600, lineHeight: 1.5,
              }}>
                {STATUS_LABELS[entry.status] ?? STATUS_LABELS.unknown}
              </span>
            </div>
            <p style={{ margin: "8px 0", color: "#6b7280", fontSize: 13 }}>
              {entry.is_local ? "Local" : "Remote"}{entry.requires_gpu ? " · GPU required" : ""}
            </p>
            <p style={{ margin: "8px 0", fontSize: 13 }}>Capabilities: {entry.categories.join(", ")}</p>
            {entry.unavailable_categories.length > 0 && (
              <p style={{ margin: "8px 0", fontSize: 13 }}>Unavailable capabilities: {entry.unavailable_categories.join(", ")}</p>
            )}
            <p style={{ margin: "8px 0", color: "#6b7280", fontSize: 13 }}>{entry.hint}</p>
            {entry.env_var && (
              <p style={{ margin: "8px 0 0", fontSize: 13 }}>
                Server environment variable: <code>{entry.env_var}</code>
              </p>
            )}
          </div>
        ))}
      </section>

      {error && (
        <div role="alert" style={{ marginTop: 16, border: "1px solid #fecaca", borderRadius: 8, background: "#fef2f2", color: "#b91c1c", padding: "10px 12px", fontSize: 13 }}>
          {error}
        </div>
      )}
    </div>
  );
}
