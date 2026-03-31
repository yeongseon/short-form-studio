import { useCallback, useEffect, useState } from "react";

interface ApiKeyStatus {
  provider: string;
  label: string;
  configured: boolean;
  masked: string;
}

const PROVIDERS: Array<{ provider: string; label: string }> = [
  { provider: "openai", label: "OpenAI" },
  { provider: "anthropic", label: "Anthropic" },
  { provider: "google", label: "Google (Gemini / Imagen)" },
  { provider: "stability", label: "Stability AI" },
  { provider: "elevenlabs", label: "ElevenLabs" },
];

const STATUS_BADGE_STYLE: Record<"configured" | "missing", React.CSSProperties> = {
  configured: {
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 8px",
    borderRadius: 999,
    background: "#dcfce7",
    color: "#166534",
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.5,
  },
  missing: {
    display: "inline-flex",
    alignItems: "center",
    padding: "2px 8px",
    borderRadius: 999,
    background: "#f3f4f6",
    color: "#4b5563",
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.5,
  },
};

export default function SettingsPage() {
  const [apiKeys, setApiKeys] = useState<ApiKeyStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [draftKey, setDraftKey] = useState("");
  const [savingProvider, setSavingProvider] = useState<string | null>(null);

  const fetchApiKeys = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/creator/settings/api-keys");
      if (!res.ok) {
        throw new Error(`Failed to load API keys (${res.status})`);
      }
      const json = (await res.json()) as ApiKeyStatus[];
      const byProvider = new Map(json.map((entry) => [entry.provider, entry]));
      const normalized = PROVIDERS.map(({ provider, label }) => {
        const found = byProvider.get(provider);
        return {
          provider,
          label,
          configured: found?.configured ?? false,
          masked: found?.masked ?? "",
        };
      });
      setApiKeys(normalized);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setApiKeys(
        PROVIDERS.map(({ provider, label }) => ({
          provider,
          label,
          configured: false,
          masked: "",
        })),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchApiKeys();
  }, [fetchApiKeys]);

  const handleEdit = useCallback((provider: string) => {
    setEditingProvider(provider);
    setDraftKey("");
    setError(null);
  }, []);

  const handleCancel = useCallback(() => {
    setEditingProvider(null);
    setDraftKey("");
  }, []);

  const handleSave = useCallback(async (provider: string) => {
    setSavingProvider(provider);
    setError(null);
    try {
      const res = await fetch("/api/creator/settings/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: draftKey }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => null) as { detail?: string } | null;
        throw new Error(body?.detail ?? `Failed to save API key (${res.status})`);
      }
      setEditingProvider(null);
      setDraftKey("");
      await fetchApiKeys();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setSavingProvider(null);
    }
  }, [draftKey, fetchApiKeys]);

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, margin: "0 0 8px" }}>Settings</h1>
      <p style={{ margin: "0 0 24px", color: "#6b7280", fontSize: 14 }}>
        Configure remote provider credentials used by model-backed generation.
      </p>

      <section style={{ border: "1px solid #e5e7eb", borderRadius: 8, background: "#fff" }}>
        <div style={{ padding: "16px 20px", borderBottom: "1px solid #e5e7eb" }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>API Keys</h2>
        </div>

        {loading ? (
          <div style={{ padding: 20, fontSize: 14, color: "#6b7280" }}>Loading API key status...</div>
        ) : (
          <div>
            {apiKeys.map((entry, index) => {
              const isEditing = editingProvider === entry.provider;
              const isSaving = savingProvider === entry.provider;
              return (
                <div
                  key={entry.provider}
                  style={{
                    padding: 20,
                    borderBottom: index < apiKeys.length - 1 ? "1px solid #f3f4f6" : "none",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: isEditing ? 12 : 0 }}>
                    <div style={{ minWidth: 220 }}>
                      <div style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>{entry.label}</div>
                      <div
                        style={{
                          fontSize: 13,
                          color: entry.configured ? "#111827" : "#6b7280",
                          marginTop: 4,
                          fontFamily: "'JetBrains Mono', monospace",
                        }}
                      >
                        {entry.configured ? entry.masked : "Not configured"}
                      </div>
                    </div>

                    <span style={entry.configured ? STATUS_BADGE_STYLE.configured : STATUS_BADGE_STYLE.missing}>
                      {entry.configured ? "Configured" : "Not configured"}
                    </span>

                    <div style={{ flex: 1 }} />

                    {!isEditing && (
                      <button
                        type="button"
                        onClick={() => handleEdit(entry.provider)}
                        style={{
                          border: "1px solid #d1d5db",
                          borderRadius: 6,
                          background: "#fff",
                          color: "#111827",
                          padding: "6px 12px",
                          fontSize: 13,
                          fontWeight: 500,
                          cursor: "pointer",
                        }}
                      >
                        Edit
                      </button>
                    )}
                  </div>

                  {isEditing && (
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input
                        type="password"
                        value={draftKey}
                        onChange={(e) => setDraftKey(e.target.value)}
                        placeholder={`Enter ${entry.label} API key`}
                        autoComplete="off"
                        style={{
                          flex: 1,
                          minWidth: 260,
                          padding: "8px 10px",
                          border: "1px solid #d1d5db",
                          borderRadius: 6,
                          fontSize: 13,
                          boxSizing: "border-box",
                        }}
                      />
                      <button
                        type="button"
                        onClick={() => void handleSave(entry.provider)}
                        disabled={isSaving}
                        style={{
                          border: "1px solid #2563eb",
                          borderRadius: 6,
                          background: isSaving ? "#93c5fd" : "#3b82f6",
                          color: "#fff",
                          padding: "8px 12px",
                          fontSize: 13,
                          fontWeight: 600,
                          cursor: isSaving ? "not-allowed" : "pointer",
                        }}
                      >
                        {isSaving ? "Saving..." : "Save"}
                      </button>
                      <button
                        type="button"
                        onClick={handleCancel}
                        disabled={isSaving}
                        style={{
                          border: "1px solid #d1d5db",
                          borderRadius: 6,
                          background: "#fff",
                          color: "#374151",
                          padding: "8px 12px",
                          fontSize: 13,
                          fontWeight: 500,
                          cursor: isSaving ? "not-allowed" : "pointer",
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>

      {error && (
        <div
          role="alert"
          style={{
            marginTop: 16,
            border: "1px solid #fecaca",
            borderRadius: 8,
            background: "#fef2f2",
            color: "#b91c1c",
            padding: "10px 12px",
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
