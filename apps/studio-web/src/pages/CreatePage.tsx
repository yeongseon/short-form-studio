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

            {/* Collapsible markdown format guide */}
            <details
              style={{
                marginBottom: 12,
                background: "#f0f7ff",
                border: "1px solid #d0e3f7",
                borderRadius: 8,
                padding: 0,
                fontSize: 13,
              }}
            >
              <summary
                style={{
                  padding: "10px 14px",
                  cursor: "pointer",
                  fontWeight: 600,
                  color: "#1a56db",
                  fontSize: 13,
                  listStyle: "none",
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span style={{ fontSize: 16 }}>📝</span> 마크다운 형식 가이드
              </summary>
              <div style={{ padding: "0 14px 14px" }}>
                <p style={{ margin: "0 0 8px", color: "#374151", lineHeight: 1.6 }}>
                  <code style={{ fontFamily: "'JetBrains Mono', monospace", background: "#e8f0fe", padding: "2px 6px", borderRadius: 3 }}>## 헤딩</code> 으로 섹션을 구분합니다. 각 섹션이 하나의 장면(scene)이 되어 이미지가 생성됩니다.
                </p>
                <p style={{ margin: "0 0 8px", color: "#374151", lineHeight: 1.6, fontSize: 12 }}>
                  섹션 이름 예시: <strong>Hook</strong>, <strong>Body 1</strong>, <strong>Body 2</strong>, <strong>CTA</strong>, <strong>Outro</strong> 등 자유롭게 지정 가능
                </p>
                <div style={{ position: "relative", marginTop: 10 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#6b7280" }}>예시 스크립트</span>
                    <button
                      type="button"
                      onClick={() => {
                        const example = `## Hook\n\n여러분, AI가 60초 만에 영상을 만들어준다면 믿으시겠어요?\n\n## Body 1\n\n최신 AI 기술을 활용하면 스크립트 작성부터 영상 렌더링까지\n모든 과정이 자동화됩니다.\n\n## Body 2\n\n텍스트를 입력하면 AI가 장면별 이미지를 생성하고,\n음성과 자막까지 자동으로 추가해줍니다.\n\n## Body 3\n\n이제 영상 제작에 전문 지식이 필요하지 않습니다.\n누구나 몇 분 만에 숏폼 콘텐츠를 만들 수 있어요.\n\n## CTA\n\n지금 바로 시작해보세요! 링크는 설명란에 있습니다.`;
                        navigator.clipboard.writeText(example);
                        setMarkdownForm((prev) => ({ ...prev, markdown: example }));
                      }}
                      style={{
                        padding: "4px 12px",
                        fontSize: 12,
                        border: "1px solid #d0e3f7",
                        borderRadius: 4,
                        background: "#fff",
                        color: "#1a56db",
                        cursor: "pointer",
                        fontWeight: 500,
                      }}
                    >
                      📋 예시 복사 & 붙여넣기
                    </button>
                  </div>
                  <pre style={{
                    fontFamily: "'JetBrains Mono', monospace",
                    fontSize: 12,
                    lineHeight: 1.6,
                    background: "#fff",
                    border: "1px solid #d0e3f7",
                    borderRadius: 6,
                    padding: 12,
                    margin: 0,
                    overflowX: "auto",
                    whiteSpace: "pre-wrap",
                    color: "#1f2937",
                  }}>{`## Hook\n\n여러분, AI가 60초 만에 영상을 만들어준다면 믿으시겠어요?\n\n## Body 1\n\n최신 AI 기술을 활용하면 스크립트 작성부터\n영상 렌더링까지 모든 과정이 자동화됩니다.\n\n## Body 2\n\n텍스트를 입력하면 AI가 장면별 이미지를 생성하고,\n음성과 자막까지 자동으로 추가해줍니다.\n\n## Body 3\n\n이제 영상 제작에 전문 지식이 필요하지 않습니다.\n누구나 몇 분 만에 숏폼 콘텐츠를 만들 수 있어요.\n\n## CTA\n\n지금 바로 시작해보세요! 링크는 설명란에 있습니다.`}</pre>
                </div>
                <table style={{ marginTop: 10, width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: "1px solid #d0e3f7" }}>
                      <th style={{ textAlign: "left", padding: "4px 8px", color: "#6b7280" }}>섹션</th>
                      <th style={{ textAlign: "left", padding: "4px 8px", color: "#6b7280" }}>Section ID</th>
                      <th style={{ textAlign: "left", padding: "4px 8px", color: "#6b7280" }}>생성 결과</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["## Hook", "hook-1", "장면 1 이미지"],
                      ["## Body 1", "body-1-2", "장면 2 이미지"],
                      ["## Body 2", "body-2-3", "장면 3 이미지"],
                      ["## Body 3", "body-3-4", "장면 4 이미지"],
                      ["## CTA", "cta-5", "장면 5 이미지"],
                    ].map(([section, id, result], i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #e5edf5" }}>
                        <td style={{ padding: "4px 8px", fontFamily: "'JetBrains Mono', monospace" }}>{section}</td>
                        <td style={{ padding: "4px 8px", fontFamily: "'JetBrains Mono', monospace", color: "#6b7280" }}>{id}</td>
                        <td style={{ padding: "4px 8px" }}>{result}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
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
