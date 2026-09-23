import { useState, useCallback, useRef } from "react";
import { DemoShortCard } from "./create/DemoShortCard";
import { useCreateProject } from "./create/useCreateProject";
import { JSON_TEMPLATE } from "./create/jsonTemplate";
import ModelSelector from "../components/creator/ModelSelector";
import IdeaForm from "../components/creator/IdeaForm";

type Tab = "idea" | "json";

interface JsonFormState {
  title: string;
  jsonScript: string;
}

const RENDER_PROFILE_OPTIONS = [
  { value: "shorts_default", label: "Shorts Default" },
  { value: "high_quality", label: "High Quality" },
  { value: "fast_preview", label: "Fast Preview" },
];
export default function CreatePage() {
  const [activeTab, setActiveTab] = useState<Tab>("idea");

  // JSON form state
  const [jsonForm, setJsonForm] = useState<JsonFormState>({
    title: "",
    jsonScript: JSON_TEMPLATE,
  });

  // Shared state
  const [stylePreset, setStylePreset] = useState("default");
  const [modelDefaults, setModelDefaults] = useState<Record<string, string>>({});

  const { submitting, error, handleIdeaSubmit, handleJsonSubmit } = useCreateProject({
    models: modelDefaults, style: stylePreset,
  });
  const ideaFormRef = useRef<HTMLDivElement>(null);

  const handleModelChange = useCallback((category: string, modelKey: string) => {
    const fieldMap: Record<string, string> = {
      script: "script_model",
      image: "image_model",
      tts: "tts_model",
      stt: "subtitle_model",
      render: "render_profile",
    };
    const field = fieldMap[category];
    if (!field) return;
    setModelDefaults((prev) => ({ ...prev, [field]: modelKey }));
  }, []);

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result;
      if (typeof text === "string") {
        setJsonForm((prev) => ({ ...prev, jsonScript: text }));
      }
    };
    reader.readAsText(file);
  }, []);

  const handleRenderProfileChange = useCallback((renderProfile: string) => {
    setModelDefaults((prev) => ({ ...prev, render_profile: renderProfile }));
  }, []);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 24 }}>Create New Project</h1>

      <DemoShortCard />

      {/* Tab list */}
      <div role="tablist" style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "2px solid #ddd" }}>
        <button
          type="button"
          role="tab"
          id="tab-idea"
          aria-selected={activeTab === "idea"}
          aria-controls="tabpanel-idea"
          onClick={() => setActiveTab("idea")}
          style={{
            padding: "8px 16px",
            border: "none",
            borderBottom: activeTab === "idea" ? "2px solid #4285f4" : "2px solid transparent",
            background: "transparent",
            cursor: "pointer",
            fontWeight: activeTab === "idea" ? 600 : 400,
            color: activeTab === "idea" ? "#4285f4" : "#666",
            fontSize: 14,
          }}
        >
          Start from Idea
        </button>
        <button
          type="button"
          role="tab"
          id="tab-json"
          aria-selected={activeTab === "json"}
          aria-controls="tabpanel-json"
          onClick={() => setActiveTab("json")}
          style={{
            padding: "8px 16px",
            border: "none",
            borderBottom: activeTab === "json" ? "2px solid #4285f4" : "2px solid transparent",
            background: "transparent",
            cursor: "pointer",
            fontWeight: activeTab === "json" ? 600 : 400,
            color: activeTab === "json" ? "#4285f4" : "#666",
            fontSize: 14,
          }}
        >
          Start from JSON
        </button>
      </div>

      {/* Idea tab panel */}
      {activeTab === "idea" && (
        <div ref={ideaFormRef} role="tabpanel" id="tabpanel-idea" aria-labelledby="tab-idea">
          <IdeaForm onSubmit={handleIdeaSubmit} submitting={submitting} error={error} />
        </div>
      )}

      {/* JSON tab panel */}
      {activeTab === "json" && (
        <div role="tabpanel" id="tabpanel-json" aria-labelledby="tab-json">
          {error && (
            <div
              data-testid="json-form-error"
              role="alert"
              style={{
                padding: "8px 12px",
                marginBottom: 16,
                background: "#fef2f2",
                border: "1px solid #fca5a5",
                borderRadius: 4,
                color: "#b91c1c",
                fontSize: 13,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="json-title" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Title
            </label>
            <input
              id="json-title"
              type="text"
              value={jsonForm.title}
              onChange={(e) => setJsonForm((prev) => ({ ...prev, title: e.target.value }))}
              disabled={submitting}
              placeholder="Project title"
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="json-content" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              JSON Script <span style={{ color: "#c00" }}>*</span>
            </label>
            <textarea
              id="json-content"
              required
              value={jsonForm.jsonScript}
              onChange={(e) => setJsonForm((prev) => ({ ...prev, jsonScript: e.target.value }))}
              disabled={submitting}
              rows={14}
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 13, fontFamily: "monospace", resize: "vertical", boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="json-upload" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Or upload a file
            </label>
            <input
              id="json-upload"
              type="file"
              accept=".json,.txt"
              onChange={handleFileUpload}
              disabled={submitting}
              style={{ fontSize: 13 }}
            />
          </div>
        </div>
      )}

      {/* Shared: Model Defaults */}
      <div style={{ marginTop: 24, padding: 16, background: "#f9f9f9", borderRadius: 8, border: "1px solid #eee" }}>
        <h2 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>Model Defaults</h2>
        <ModelSelector categories={activeTab === "idea" ? ["script", "image"] : ["image"]} onSelectionChange={handleModelChange} />
        <div style={{ marginTop: 12 }}>
          <label htmlFor="render-profile" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
            Render Profile
          </label>
          <select
            id="render-profile"
            value={modelDefaults.render_profile ?? "shorts_default"}
            onChange={(e) => handleRenderProfileChange(e.target.value)}
            style={{ padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14 }}
          >
            {RENDER_PROFILE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Shared: Style Preset */}
      <div style={{ marginTop: 16 }}>
        <label htmlFor="style-preset" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
          Style Preset
        </label>
        <select
          id="style-preset"
          value={stylePreset}
          onChange={(e) => setStylePreset(e.target.value)}
          style={{ padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14 }}
        >
          <option value="default">default</option>
          <option value="cinematic">cinematic</option>
          <option value="dynamic">dynamic</option>
          <option value="minimal">minimal</option>
        </select>
      </div>

      {/* Submit */}
      <div style={{ marginTop: 24 }}>
        <button
          type="button"
          disabled={submitting}
          onClick={activeTab === "idea" ? () => {
            const form = ideaFormRef.current?.querySelector<HTMLFormElement>('form');
            form?.requestSubmit();
          } : () => handleJsonSubmit(jsonForm)}
          style={{
            padding: "10px 24px",
            background: submitting ? "#93b4f4" : "#4285f4",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "Creating…" : "Create Project"}
        </button>
      </div>
    </div>
  );
}
