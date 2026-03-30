import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import ModelSelector from "../components/creator/ModelSelector";
import IdeaForm, { type IdeaFormData } from "../components/creator/IdeaForm";

type Tab = "idea" | "markdown";

interface MarkdownFormState {
  title: string;
  markdown: string;
}

const API_BASE = "/api/creator";

export default function CreatePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("idea");

  // Markdown form state
  const [markdownForm, setMarkdownForm] = useState<MarkdownFormState>({
    title: "",
    markdown: "",
  });

  // Shared state
  const [stylePreset, setStylePreset] = useState("default");
  const [modelDefaults, setModelDefaults] = useState<Record<string, string>>({});

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Stable ref for modelDefaults so IdeaForm submit handler always has latest
  const modelDefaultsRef = useRef(modelDefaults);
  modelDefaultsRef.current = modelDefaults;
  const stylePresetRef = useRef(stylePreset);
  stylePresetRef.current = stylePreset;

  const handleModelChange = useCallback((category: string, modelKey: string) => {
    setModelDefaults((prev) => ({ ...prev, [category]: modelKey }));
  }, []);

  const handleFileUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result;
      if (typeof text === "string") {
        setMarkdownForm((prev) => ({ ...prev, markdown: text }));
      }
    };
    reader.readAsText(file);
  }, []);

  const handleIdeaSubmit = useCallback(
    async (data: IdeaFormData) => {
      setSubmitting(true);
      setError(null);

      try {
        // 1. Create project
        const projRes = await fetch(`${API_BASE}/projects`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: data.title,
            source_type: "idea",
            idea_brief: data.ideaBrief,
          }),
        });

        if (!projRes.ok) {
          const body = await projRes.json().catch(() => null);
          throw new Error(body?.detail ?? `Failed to create project (${projRes.status})`);
        }

        const project = await projRes.json();

        // 2. Create run
        const runRes = await fetch(`${API_BASE}/projects/${project.id}/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            model_defaults: modelDefaultsRef.current,
            style_preset: stylePresetRef.current,
            metadata: {
              content_goal: data.contentGoal || undefined,
              target_duration: data.targetDuration,
            },
          }),
        });

        if (!runRes.ok) {
          const body = await runRes.json().catch(() => null);
          throw new Error(body?.detail ?? `Failed to create run (${runRes.status})`);
        }

        // 3. Navigate to project page
        navigate(`/projects/${project.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "An unexpected error occurred");
      } finally {
        setSubmitting(false);
      }
    },
    [navigate],
  );

  const handleMarkdownSubmit = useCallback(async () => {
    const title = markdownForm.title.trim();
    const markdown = markdownForm.markdown.trim();
    if (!markdown) return;

    setSubmitting(true);
    setError(null);

    try {
      // 1. Create project
      const projRes = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title || "Untitled",
          source_type: "markdown",
          markdown_source: markdown,
        }),
      });

      if (!projRes.ok) {
        const body = await projRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Failed to create project (${projRes.status})`);
      }

      const project = await projRes.json();

      // 2. Import markdown (creates run + saves draft in one call)
      const importRes = await fetch(`${API_BASE}/projects/${project.id}/script/import-markdown`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          markdown,
          model_defaults: modelDefaultsRef.current,
          style_preset: stylePresetRef.current,
        }),
      });

      if (!importRes.ok) {
        const body = await importRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Failed to import markdown (${importRes.status})`);
      }

      // 3. Navigate to project page
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setSubmitting(false);
    }
  }, [markdownForm, navigate]);

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 24 }}>Create New Project</h1>

      {/* Tab list */}
      <div role="tablist" style={{ display: "flex", gap: 4, marginBottom: 16, borderBottom: "2px solid #ddd" }}>
        <button
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
          role="tab"
          id="tab-markdown"
          aria-selected={activeTab === "markdown"}
          aria-controls="tabpanel-markdown"
          onClick={() => setActiveTab("markdown")}
          style={{
            padding: "8px 16px",
            border: "none",
            borderBottom: activeTab === "markdown" ? "2px solid #4285f4" : "2px solid transparent",
            background: "transparent",
            cursor: "pointer",
            fontWeight: activeTab === "markdown" ? 600 : 400,
            color: activeTab === "markdown" ? "#4285f4" : "#666",
            fontSize: 14,
          }}
        >
          Start from Markdown
        </button>
      </div>

      {/* Idea tab panel */}
      {activeTab === "idea" && (
        <div role="tabpanel" id="tabpanel-idea" aria-labelledby="tab-idea">
          <IdeaForm onSubmit={handleIdeaSubmit} submitting={submitting} error={error} />
        </div>
      )}

      {/* Markdown tab panel */}
      {activeTab === "markdown" && (
        <div role="tabpanel" id="tabpanel-markdown" aria-labelledby="tab-markdown">
          {error && (
            <div
              data-testid="markdown-form-error"
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
            <label htmlFor="md-title" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Title
            </label>
            <input
              id="md-title"
              type="text"
              value={markdownForm.title}
              onChange={(e) => setMarkdownForm((prev) => ({ ...prev, title: e.target.value }))}
              disabled={submitting}
              placeholder="Project title"
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="md-content" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Markdown Content <span style={{ color: "#c00" }}>*</span>
            </label>
            <textarea
              id="md-content"
              required
              value={markdownForm.markdown}
              onChange={(e) => setMarkdownForm((prev) => ({ ...prev, markdown: e.target.value }))}
              disabled={submitting}
              placeholder="Paste your script markdown here..."
              rows={10}
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, fontFamily: "monospace", resize: "vertical", boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="md-upload" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Or upload a file
            </label>
            <input
              id="md-upload"
              type="file"
              accept=".md,.txt"
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
        <ModelSelector categories={["script", "image"]} onSelectionChange={handleModelChange} />
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
            const form = document.querySelector<HTMLFormElement>('[data-testid="idea-form"]');
            form?.requestSubmit();
          } : handleMarkdownSubmit}
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
