import { useEffect, useState, useCallback, useRef } from "react";

/** Shape of a single model entry returned by GET /api/creator/models. */
interface ModelEntry {
  key: string;
  label: string;
  provider_type: string;
  is_local: boolean;
  requires_gpu: boolean;
  status: "available" | "unavailable" | "unknown";
}

/** Full response shape from the models endpoint. */
interface ModelsResponse {
  script_models: ModelEntry[];
  image_models: ModelEntry[];
  tts_models: ModelEntry[];
  stt_models: ModelEntry[];
}

interface ApiKeyStatus {
  provider: string;
  label: string;
  configured: boolean;
  masked: string;
}

/** Category metadata for rendering. */
interface CategoryMeta {
  responseKey: keyof ModelsResponse;
  displayName: string;
}

const CATEGORY_MAP: Record<string, CategoryMeta> = {
  script: { responseKey: "script_models", displayName: "Script Model" },
  image: { responseKey: "image_models", displayName: "Image Model" },
  tts: { responseKey: "tts_models", displayName: "TTS Model" },
  stt: { responseKey: "stt_models", displayName: "STT Model" },
};

const ALL_CATEGORIES = Object.keys(CATEGORY_MAP);

const PROVIDER_TYPE_MAP: Record<string, string> = {
  openai_llm: "openai",
  openai_image: "openai",
  openai_tts: "openai",
  anthropic_llm: "anthropic",
  gemini_llm: "google",
  google_image: "google",
  stability_image: "stability",
  elevenlabs_tts: "elevenlabs",
};

export interface ModelSelectorProps {
  /** Explicit selection map: category → model key. Enables controlled mode. */
  selectedModels?: Record<string, string>;
  /** Called when the user selects a model, or when defaults are computed on load. */
  onSelectionChange?: (category: string, modelKey: string) => void;
  /** Subset of categories to display. Defaults to all. */
  categories?: string[];
  /** API base URL override (for testing). Defaults to "" (relative). */
  apiBase?: string;
}

const STATUS_STYLES: Record<string, React.CSSProperties> = {
  available: { background: "#d4edda", color: "#155724", borderRadius: 4, padding: "2px 6px", fontSize: 11 },
  unavailable: { background: "#f8d7da", color: "#721c24", borderRadius: 4, padding: "2px 6px", fontSize: 11 },
  unknown: { background: "#fff3cd", color: "#856404", borderRadius: 4, padding: "2px 6px", fontSize: 11 },
};

export default function ModelSelector({
  selectedModels,
  onSelectionChange,
  categories,
  apiBase = "",
}: ModelSelectorProps) {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [localSelection, setLocalSelection] = useState<Record<string, string>>({});
  const [defaultsVersion, setDefaultsVersion] = useState(0);
  const [configuredProviders, setConfiguredProviders] = useState<Record<string, boolean>>({});

  const visibleCategories = categories ?? ALL_CATEGORIES;

  // Stable ref for onSelectionChange to avoid effect re-fires when callback identity changes
  const onChangeRef = useRef(onSelectionChange);
  onChangeRef.current = onSelectionChange;

  const localSelectionRef = useRef(localSelection);
  localSelectionRef.current = localSelection;

  // Ref to stage newly-computed defaults for notification in a follow-up effect.
  // Keeping notification out of the setLocalSelection updater keeps it pure.
  const pendingDefaultsRef = useRef<Array<[string, string]>>([]);

  // Effect 1: Fetch model catalog when apiBase changes
  useEffect(() => {
    let cancelled = false;

    async function fetchModels() {
      setLoading(true);
      setError(null);
      try {
        const [modelsRes, apiKeysRes] = await Promise.all([
          fetch(`${apiBase}/api/creator/models`),
          fetch(`${apiBase}/api/creator/settings/api-keys`),
        ]);

        if (!modelsRes.ok) {
          throw new Error(`Failed to fetch models: ${modelsRes.status}`);
        }
        const json: ModelsResponse = await modelsRes.json();

        let providerStatus: Record<string, boolean> = {};
        if (apiKeysRes.ok) {
          const apiKeysJson = await apiKeysRes.json();
          if (Array.isArray(apiKeysJson)) {
            providerStatus = (apiKeysJson as ApiKeyStatus[]).reduce<Record<string, boolean>>((acc, item) => {
              acc[item.provider] = item.configured;
              return acc;
            }, {});
          }
        }

        if (!cancelled) {
          setData(json);
          setConfiguredProviders(providerStatus);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    fetchModels();
    return () => {
      cancelled = true;
    };
  }, [apiBase]);

  // Stable string key for categories to avoid re-triggering effect on array identity changes.
  const categoriesKey = visibleCategories.join(",");

  // Effect 2: Derive default selections when data or visible categories change (uncontrolled mode only).
  // Only initializes selections for categories that don't already have a user-chosen value,
  // so manual selections survive parent re-renders and categories changes.
  // The updater is kept pure — side-effect notification is staged via ref.
  useEffect(() => {
    if (!data || selectedModels) return;

    const cats = categoriesKey.split(",");
    const prev = localSelectionRef.current;
    const next = { ...prev };
    const newDefaults: Array<[string, string]> = [];

    for (const cat of cats) {
      if (next[cat]) {
        const meta = CATEGORY_MAP[cat];
        if (meta) {
          const models = data[meta.responseKey];
          const stillExists = models.some((m) => m.key === next[cat]);
          if (stillExists) continue;
        }
      }

      const meta = CATEGORY_MAP[cat];
      if (!meta) continue;
      const models = data[meta.responseKey];
      const firstAvailable = models.find((m) => m.status === "available") ?? models[0];
      if (firstAvailable) {
        next[cat] = firstAvailable.key;
        newDefaults.push([cat, firstAvailable.key]);
      }
    }

    if (newDefaults.length > 0) {
      pendingDefaultsRef.current = newDefaults;
      setLocalSelection(next);
      setDefaultsVersion((prevVersion) => prevVersion + 1);
    }
  }, [data, categoriesKey, selectedModels]);

  // Effect 3: Notify parent of newly-computed defaults after state has settled.
  // Runs after localSelection changes; checks the staged ref to avoid duplicate calls.
  useEffect(() => {
    const pending = pendingDefaultsRef.current;
    if (pending.length === 0) return;
    pendingDefaultsRef.current = [];

    const cb = onChangeRef.current;
    if (cb) {
      for (const [cat, key] of pending) {
        cb(cat, key);
      }
    }
  }, [defaultsVersion]);

  const handleSelect = useCallback(
    (category: string, modelKey: string) => {
      if (!selectedModels) {
        setLocalSelection((prev) => ({ ...prev, [category]: modelKey }));
      }
      onSelectionChange?.(category, modelKey);
    },
    [selectedModels, onSelectionChange],
  );

  const activeSelection = selectedModels ?? localSelection;

  if (loading) {
    return <div data-testid="model-selector-loading">Loading models…</div>;
  }

  if (error) {
    return <div data-testid="model-selector-error" style={{ color: "#721c24" }}>Error: {error}</div>;
  }

  if (!data) {
    return null;
  }

  return (
    <div data-testid="model-selector">
      {visibleCategories.map((cat) => {
        const meta = CATEGORY_MAP[cat];
        if (!meta) return null;
        const models = [...data[meta.responseKey]].sort((a, b) => Number(a.is_local) === Number(b.is_local) ? 0 : (a.is_local ? -1 : 1));
        const groupName = `model-${cat}`;

        return (
          <fieldset key={cat} style={{ marginBottom: 16, border: "1px solid #ddd", borderRadius: 6, padding: 12 }}>
            <legend style={{ fontWeight: 600, fontSize: 14 }}>{meta.displayName}</legend>
            {models.length === 0 ? (
              <div style={{ color: "#888", fontSize: 13 }}>No models available</div>
            ) : (
              <div role="radiogroup" aria-label={meta.displayName}>
                {models.map((model) => {
                  const isSelected = activeSelection[cat] === model.key;
                  const inputId = `${groupName}-${model.key}`;
                  const mappedProvider = PROVIDER_TYPE_MAP[model.provider_type];
                  const needsApiKeyWarning = !model.is_local && Boolean(mappedProvider) && !configuredProviders[mappedProvider];
                  return (
                    <label
                      key={model.key}
                      htmlFor={inputId}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "6px 8px",
                        cursor: "pointer",
                        borderRadius: 4,
                        background: isSelected ? "#e8f0fe" : "transparent",
                        border: isSelected ? "1px solid #4285f4" : "1px solid transparent",
                        marginBottom: 4,
                      }}
                    >
                      <input
                        type="radio"
                        id={inputId}
                        name={groupName}
                        value={model.key}
                        checked={isSelected}
                        onChange={() => handleSelect(cat, model.key)}
                        style={{ margin: 0 }}
                      />
                      <span style={{ flex: 1, fontSize: 13 }}>{model.label}</span>
                      <span style={STATUS_STYLES[model.status] ?? STATUS_STYLES.unknown}>
                        {model.status}
                      </span>
                      {model.is_local ? (
                        <span style={{ fontSize: 10, color: "#1f2937", background: "#e5e7eb", borderRadius: 3, padding: "1px 4px" }}>
                          Local
                        </span>
                      ) : (
                        <span style={{ fontSize: 10, color: "#1d4ed8", background: "#dbeafe", borderRadius: 3, padding: "1px 4px" }}>
                          Remote
                        </span>
                      )}
                      {needsApiKeyWarning && (
                        <span style={{ fontSize: 11, color: "#c2410c", fontWeight: 500 }}>
                          ⚠ API key required
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>
        );
      })}
    </div>
  );
}
