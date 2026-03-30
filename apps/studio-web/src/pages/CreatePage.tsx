import { useState, useCallback } from "react";
import ModelSelector from "../components/creator/ModelSelector";

type Tab = "idea" | "markdown";

interface IdeaFormState {
  title: string;
  ideaBrief: string;
  targetDuration: number;
  contentGoal: string;
}

interface MarkdownFormState {
  title: string;
  markdown: string;
}

export default function CreatePage() {
  const [activeTab, setActiveTab] = useState<Tab>("idea");

  // Idea form state
  const [ideaForm, setIdeaForm] = useState<IdeaFormState>({
    title: "",
    ideaBrief: "",
    targetDuration: 60,
    contentGoal: "",
  });

  // Markdown form state
  const [markdownForm, setMarkdownForm] = useState<MarkdownFormState>({
    title: "",
    markdown: "",
  });

  // Shared state
  const [stylePreset, setStylePreset] = useState("default");
  const [modelDefaults, setModelDefaults] = useState<Record<string, string>>({});

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

  const handleSubmit = useCallback(() => {
    const formData = {
      tab: activeTab,
      ...(activeTab === "idea" ? ideaForm : markdownForm),
      stylePreset,
      modelDefaults,
    };
    // eslint-disable-next-line no-console
    console.log("CreatePage submit (stub):", formData);
  }, [activeTab, ideaForm, markdownForm, stylePreset, modelDefaults]);

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
          <div style={{ marginBottom: 16 }}>
            <label htmlFor="idea-title" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Title <span style={{ color: "#c00" }}>*</span>
            </label>
            <input
              id="idea-title"
              type="text"
              required
              value={ideaForm.title}
              onChange={(e) => setIdeaForm((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="Project title"
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="idea-brief" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Idea Brief <span style={{ color: "#c00" }}>*</span>
            </label>
            <textarea
              id="idea-brief"
              required
              value={ideaForm.ideaBrief}
              onChange={(e) => setIdeaForm((prev) => ({ ...prev, ideaBrief: e.target.value }))}
              placeholder="Describe your video idea..."
              rows={4}
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, resize: "vertical", boxSizing: "border-box" }}
            />
          </div>

          <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
            <div style={{ flex: 1 }}>
              <label htmlFor="target-duration" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
                Target Duration (seconds)
              </label>
              <input
                id="target-duration"
                type="number"
                min={10}
                max={180}
                value={ideaForm.targetDuration}
                onChange={(e) => setIdeaForm((prev) => ({ ...prev, targetDuration: Number(e.target.value) }))}
                style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
              />
            </div>
            <div style={{ flex: 1 }}>
              <label htmlFor="content-goal" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
                Content Goal
              </label>
              <input
                id="content-goal"
                type="text"
                value={ideaForm.contentGoal}
                onChange={(e) => setIdeaForm((prev) => ({ ...prev, contentGoal: e.target.value }))}
                placeholder="e.g., educational, entertainment"
                style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Markdown tab panel */}
      {activeTab === "markdown" && (
        <div role="tabpanel" id="tabpanel-markdown" aria-labelledby="tab-markdown">
          <div style={{ marginBottom: 16 }}>
            <label htmlFor="md-title" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Title
            </label>
            <input
              id="md-title"
              type="text"
              value={markdownForm.title}
              onChange={(e) => setMarkdownForm((prev) => ({ ...prev, title: e.target.value }))}
              placeholder="Project title"
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #ccc", borderRadius: 4, fontSize: 14, boxSizing: "border-box" }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label htmlFor="md-content" style={{ display: "block", fontWeight: 600, marginBottom: 4, fontSize: 13 }}>
              Markdown Content
            </label>
            <textarea
              id="md-content"
              value={markdownForm.markdown}
              onChange={(e) => setMarkdownForm((prev) => ({ ...prev, markdown: e.target.value }))}
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
          onClick={handleSubmit}
          style={{
            padding: "10px 24px",
            background: "#4285f4",
            color: "#fff",
            border: "none",
            borderRadius: 6,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Create Project
        </button>
      </div>
    </div>
  );
}
