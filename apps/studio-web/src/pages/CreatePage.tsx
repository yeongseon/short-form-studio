import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import ModelSelector from "../components/creator/ModelSelector";
import IdeaForm, { type IdeaFormData } from "../components/creator/IdeaForm";

type Tab = "idea" | "json";

interface JsonFormState {
  title: string;
  jsonScript: string;
}

const API_BASE = "/api/creator";
const RENDER_PROFILE_OPTIONS = [
  { value: "shorts_default", label: "Shorts Default" },
  { value: "high_quality", label: "High Quality" },
  { value: "fast_preview", label: "Fast Preview" },
];
const JSON_TEMPLATE = JSON.stringify(
  {
    scenes: [
      {
        type: "hook",
        text: "여러분, AI가 60초 만에 영상을 만들어준다면 믿으시겠어요?",
        image_prompt:
          "A futuristic holographic AI interface floating in a dark studio, cinematic blue light",
        speaker: "host",
        mood: "exciting",
        composition: "medium shot, centered",
        style_tags: ["cinematic", "sci-fi"],
      },
      {
        type: "body",
        text: "최신 AI 기술을 활용하면 스크립트 작성부터 영상 렌더링까지 모든 과정이 자동화됩니다.",
        image_prompt:
          "Split screen showing code on left and rendered video on right, modern tech aesthetic",
        speaker: "host",
        mood: "informative",
        composition: "wide shot",
        style_tags: ["tech", "modern"],
      },
      {
        type: "body",
        text: "텍스트를 입력하면 AI가 장면별 이미지를 생성하고, 음성과 자막까지 자동으로 추가해줍니다.",
        image_prompt:
          "Hands typing on a glowing keyboard with AI-generated images appearing on screen",
        speaker: "host",
        mood: "demonstrative",
        composition: "close-up on hands and screen",
        style_tags: ["tech", "hands-on"],
      },
      {
        type: "cta",
        text: "지금 바로 시작해보세요! 링크는 설명란에 있습니다.",
        image_prompt:
          "Bright call-to-action screen with arrow pointing down, energetic gradient background",
        speaker: "host",
        mood: "urgent",
        composition: "centered text overlay",
        style_tags: ["vibrant", "cta"],
      },
    ],
  },
  null,
  2,
);


export default function CreatePage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<Tab>("idea");

  // JSON form state
  const [jsonForm, setJsonForm] = useState<JsonFormState>({
    title: "",
    jsonScript: JSON_TEMPLATE,
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

  const handleJsonSubmit = useCallback(async () => {
    const title = jsonForm.title.trim();
    const jsonScript = jsonForm.jsonScript.trim();
    if (!jsonScript) return;

    // Validate JSON locally before sending
    try {
      JSON.parse(jsonScript);
    } catch {
      setError("Invalid JSON — please check the syntax.");
      return;
    }

    setSubmitting(true);
    setError(null);

    try {
      // 1. Create project
      const projRes = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: title || "Untitled",
          source_type: "pasted_json",
          json_script: jsonScript,
        }),
      });

      if (!projRes.ok) {
        const body = await projRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Failed to create project (${projRes.status})`);
      }

      const project = await projRes.json();

      // 2. Import JSON (creates run + saves structured draft in one call)
      const importRes = await fetch(`${API_BASE}/projects/${project.id}/script/import-json`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          json_script: jsonScript,
          model_defaults: modelDefaultsRef.current,
          style_preset: stylePresetRef.current,
        }),
      });

      if (!importRes.ok) {
        const body = await importRes.json().catch(() => null);
        throw new Error(body?.detail ?? `Failed to import JSON (${importRes.status})`);
      }

      // 3. Navigate to project page
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setSubmitting(false);
    }
  }, [jsonForm, navigate]);

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
        <div role="tabpanel" id="tabpanel-idea" aria-labelledby="tab-idea">
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
            const form = document.querySelector<HTMLFormElement>('[data-testid="idea-form"]');
            form?.requestSubmit();
          } : handleJsonSubmit}
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
