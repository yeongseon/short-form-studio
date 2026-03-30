import { useEffect, useState, useCallback } from "react";

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

export interface ModelSelectorProps {
  /** Explicit selection map: category → model key. Enables override mode. */
  selectedModels?: Record<string, string>;
  /** Called when the user selects a model. */
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

  const visibleCategories = categories ?? ALL_CATEGORIES;

  useEffect(() => {
    let cancelled = false;

    async function fetchModels() {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${apiBase}/api/creator/models`);
        if (!res.ok) {
          throw new Error(`Failed to fetch models: ${res.status}`);
        }
        const json: ModelsResponse = await res.json();
        if (!cancelled) {
          setData(json);

          // Default-selection mode: pick first available model per category
          const defaults: Record<string, string> = {};
          for (const cat of visibleCategories) {
            const meta = CATEGORY_MAP[cat];
            if (!meta) continue;
            const models = json[meta.responseKey];
            const firstAvailable = models.find((m) => m.status === "available") ?? models[0];
            if (firstAvailable) {
              defaults[cat] = firstAvailable.key;
            }
          }
          setLocalSelection(defaults);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBase]);

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
        const models = data[meta.responseKey];

        return (
          <fieldset key={cat} style={{ marginBottom: 16, border: "1px solid #ddd", borderRadius: 6, padding: 12 }}>
            <legend style={{ fontWeight: 600, fontSize: 14 }}>{meta.displayName}</legend>
            {models.length === 0 ? (
              <div style={{ color: "#888", fontSize: 13 }}>No models available</div>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {models.map((model) => {
                  const isSelected = activeSelection[cat] === model.key;
                  return (
                    <li
                      key={model.key}
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => handleSelect(cat, model.key)}
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
                      <span style={{ flex: 1, fontSize: 13 }}>{model.label}</span>
                      <span style={STATUS_STYLES[model.status] ?? STATUS_STYLES.unknown}>
                        {model.status}
                      </span>
                      {model.is_local && (
                        <span style={{ fontSize: 10, color: "#666", background: "#eee", borderRadius: 3, padding: "1px 4px" }}>
                          local
                        </span>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </fieldset>
        );
      })}
    </div>
  );
}
