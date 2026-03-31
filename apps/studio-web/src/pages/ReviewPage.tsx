/**
 * ReviewPage — read-only review of a run's outputs at various stages.
 *
 * Fetches the run detail plus preview artifacts and renders:
 * - PipelineStepper (header progress bar)
 * - Script section (from GET /runs/:runId/script)
 * - Visual plan section (from GET /runs/:runId/visual-plan)
 * - Visual assets section (from GET /runs/:runId/visual-assets)
 * - Audio / subtitle / video preview metadata (from GET /runs/:runId/preview)
 * - Links back to the ProjectPage editor for each stage
 */

import { useState, useEffect, useCallback } from "react";
import { useParams, Link } from "react-router-dom";

import PipelineStepper from "../components/creator/PipelineStepper";

const API_BASE = "/api/creator";

/** Convert API artifact path → browser-accessible URL via Vite proxy. */
function artifactUrl(path: string): string {
  const match = path.match(/data\/artifacts\/(.*)/);
  return match ? `/artifacts/${match[1]}` : `/artifacts/${path}`;
}

// --------------- types ---------------

interface RunDetail {
  id: number;
  project_id: number;
  current_stage: string;
  status: string;
  restart_from: string | null;
}

interface PreviewData {
  run_id: number;
  current_stage: string;
  video: {
    id: number;
    path: string;
    render_profile: string | null;
    created_at: string;
  } | null;
  audio: {
    id: number;
    path: string;
    model_used: string;
    created_at: string;
  } | null;
  subtitle: {
    id: number;
    path: string;
    format: string;
    created_at: string;
  } | null;
}

interface ScriptData {
  script: string | null;
  structured_script: Record<string, unknown> | null;
}

interface VisualPlanScene {
  scene_id: string;
  description: string;
  image_prompt: string;
}

// Stages that have passed script
const POST_SCRIPT_STAGES = new Set([
  "SCRIPT_REVIEW",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_PLAN_REVIEW",
  "VISUAL_ASSET_GENERATING",
  "VISUAL_ASSET_REVIEW",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

const POST_VISUAL_PLAN_STAGES = new Set([
  "VISUAL_PLAN_REVIEW",
  "VISUAL_ASSET_GENERATING",
  "VISUAL_ASSET_REVIEW",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

const POST_VISUAL_ASSET_STAGES = new Set([
  "VISUAL_ASSET_REVIEW",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

const POST_AUDIO_STAGES = new Set([
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
  "FINAL_REVIEW",
  "PUBLISHED",
]);

// --------------- styles ---------------

const cardStyle: React.CSSProperties = {
  marginBottom: 24,
  padding: 20,
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  background: "#fff",
};

const headerStyle: React.CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: 12,
};

const sectionTitle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  margin: 0,
};

const metaStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#6b7280",
};

const editLinkStyle: React.CSSProperties = {
  fontSize: 12,
  color: "#4285f4",
  textDecoration: "none",
};

const previewBoxStyle: React.CSSProperties = {
  padding: 12,
  background: "#f9fafb",
  borderRadius: 6,
  fontSize: 13,
  fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", monospace',
  whiteSpace: "pre-wrap",
  overflowX: "auto",
  maxHeight: 300,
  overflowY: "auto",
};

// --------------- component ---------------

export default function ReviewPage() {
  const { runId } = useParams<{ runId: string }>();
  const numericRunId = Number(runId);

  const [run, setRun] = useState<RunDetail | null>(null);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [script, setScript] = useState<ScriptData | null>(null);
  const [scenes, setScenes] = useState<VisualPlanScene[]>([]);
  const [assets, setAssets] = useState<Record<string, { asset_path: string; model_used: string; is_active: boolean }[]>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [subtitleContent, setSubtitleContent] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch run detail
      const runRes = await fetch(`${API_BASE}/runs/${numericRunId}`);
      if (!runRes.ok) {
        if (runRes.status === 404) throw new Error("Run not found");
        throw new Error(`Failed to load run (${runRes.status})`);
      }
      const runData: RunDetail = await runRes.json();
      setRun(runData);

      const stage = runData.current_stage;

      // Fetch script if past idea
      if (POST_SCRIPT_STAGES.has(stage)) {
        const scriptRes = await fetch(`${API_BASE}/runs/${numericRunId}/script`);
        if (scriptRes.ok) {
          setScript(await scriptRes.json());
        }
      }

      // Fetch visual plan if past script
      if (POST_VISUAL_PLAN_STAGES.has(stage)) {
        const vpRes = await fetch(`${API_BASE}/runs/${numericRunId}/visual-plan`);
        if (vpRes.ok) {
          const vpData = await vpRes.json();
          setScenes(vpData.scenes ?? []);
        }
      }

      // Fetch visual assets if past visual plan
      if (POST_VISUAL_ASSET_STAGES.has(stage)) {
        const assetsRes = await fetch(`${API_BASE}/runs/${numericRunId}/visual-assets`);
        if (assetsRes.ok) {
          const assetsData = await assetsRes.json();
          setAssets(assetsData.scenes ?? {});
        }
      }

      // Fetch preview (audio/subtitle/video) if past visual assets
      if (POST_AUDIO_STAGES.has(stage)) {
        const previewRes = await fetch(`${API_BASE}/runs/${numericRunId}/preview`);
        if (previewRes.ok) {
          setPreview(await previewRes.json());
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "An unexpected error occurred");
    } finally {
      setLoading(false);
    }
  }, [numericRunId]);

  useEffect(() => {
    if (!Number.isNaN(numericRunId)) {
      fetchAll();
    }
  }, [numericRunId, fetchAll]);

  // Fetch subtitle content when preview is available
  useEffect(() => {
    if (!preview?.subtitle?.path) {
      setSubtitleContent(null);
      return;
    }
    setSubtitleContent(null); // reset before fetching
    const url = artifactUrl(preview.subtitle.path);
    let cancelled = false;
    fetch(url)
      .then((res) => (res.ok ? res.text() : Promise.reject(res.status)))
      .then((text) => { if (!cancelled) setSubtitleContent(text); })
      .catch(() => { if (!cancelled) setSubtitleContent("(Failed to load subtitle content)"); });
    return () => { cancelled = true; };
  }, [preview?.subtitle?.path]);

  // ---- render ----

  if (Number.isNaN(numericRunId)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p style={{ color: "#b91c1c" }}>Invalid run ID.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>Back to projects</Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div
        role="status"
        aria-label="Loading review"
        style={{ maxWidth: 720, margin: "0 auto", padding: 24, textAlign: "center", color: "#6b7280" }}
      >
        Loading review...
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <div
          role="alert"
          style={{
            padding: "12px 16px",
            background: "#fef2f2",
            border: "1px solid #fca5a5",
            borderRadius: 6,
            color: "#b91c1c",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
        <Link to="/runs" style={{ color: "#4285f4", fontSize: 13 }}>Back to projects</Link>
      </div>
    );
  }

  if (!run) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p>Run not found.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>Back to projects</Link>
      </div>
    );
  }

  const stage = run.current_stage;
  const isFailed = run.status === "failed";
  const editUrl = `/projects/${run.project_id}`;

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
      {/* Header */}
      <div style={{ marginBottom: 16 }}>
        <Link to="/runs" style={{ color: "#6b7280", fontSize: 12, textDecoration: "none" }}>
          &larr; Projects
        </Link>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 4px" }}>
          Review &mdash; Run #{run.id}
        </h1>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          Stage: {stage} &middot; Status: {run.status}
          {isFailed && <span style={{ color: "#b91c1c", fontWeight: 600 }}> (FAILED)</span>}
        </span>
      </div>

      {/* Pipeline stepper */}
      <div style={{ marginBottom: 24 }}>
        <PipelineStepper currentStage={stage} failed={isFailed} />
      </div>

      {/* Script section */}
      {script && (
        <div style={cardStyle} data-testid="review-script-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Script</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          <div style={previewBoxStyle}>
            {script.script ?? "(No script content)"}
          </div>
        </div>
      )}

      {/* Visual Plan section */}
      {scenes.length > 0 && (
        <div style={cardStyle} data-testid="review-visual-plan-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Visual Plan ({scenes.length} scenes)</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {scenes.map((scene) => (
              <div
                key={scene.scene_id}
                style={{
                  padding: 12,
                  background: "#f9fafb",
                  borderRadius: 6,
                  border: "1px solid #e5e7eb",
                }}
              >
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>
                  {scene.scene_id}
                </div>
                <div style={{ fontSize: 13, color: "#374151", marginBottom: 4 }}>
                  {scene.description}
                </div>
                <div style={metaStyle}>Prompt: {scene.image_prompt}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Visual Assets section */}
      {Object.keys(assets).length > 0 && (
        <div style={cardStyle} data-testid="review-assets-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Visual Assets</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {Object.entries(assets).map(([sceneId, sceneAssets]) => (
              <div key={sceneId}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>{sceneId}</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
                  {sceneAssets.map((asset, idx) => (
                    <div
                      key={idx}
                      style={{
                        background: asset.is_active ? "#f0fdf4" : "#f9fafb",
                        borderRadius: 6,
                        border: asset.is_active ? "1px solid #bbf7d0" : "1px solid #e5e7eb",
                        overflow: "hidden",
                      }}
                    >
                      <img
                        src={artifactUrl(asset.asset_path)}
                        alt={`${sceneId} asset ${idx + 1}`}
                        style={{
                          width: "100%",
                          aspectRatio: "9 / 16",
                          objectFit: "cover",
                          display: "block",
                          background: "#e5e7eb",
                        }}
                      />
                      <div style={{ padding: "6px 8px" }}>
                        <div style={{ fontSize: 11, color: "#374151", wordBreak: "break-all" }}>
                          {asset.asset_path.split("/").pop()}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
                          <span style={metaStyle}>Model: {asset.model_used}</span>
                          {asset.is_active && (
                            <span style={{ fontSize: 10, color: "#166534", fontWeight: 600, background: "#dcfce7", padding: "1px 5px", borderRadius: 3 }}>
                              ACTIVE
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Audio section */}
      {preview?.audio && (
        <div style={cardStyle} data-testid="review-audio-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Audio</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          <audio
            controls
            style={{ width: "100%", marginBottom: 8, borderRadius: 6 }}
            src={artifactUrl(preview.audio.path)}
          />
          <div style={{ fontSize: 13 }}>
            <div><strong>Model:</strong> {preview.audio.model_used}</div>
            <div style={metaStyle}>Created: {new Date(preview.audio.created_at).toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* Subtitle section */}
      {preview?.subtitle && (
        <div style={cardStyle} data-testid="review-subtitle-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Subtitles</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          {subtitleContent !== null ? (
            <div style={previewBoxStyle}>{subtitleContent}</div>
          ) : (
            <div style={{ fontSize: 13, color: "#6b7280", fontStyle: "italic" }}>
              Loading subtitle content…
            </div>
          )}
          <div style={{ fontSize: 13, marginTop: 8 }}>
            <div><strong>Format:</strong> {preview.subtitle.format}</div>
            <div style={metaStyle}>Created: {new Date(preview.subtitle.created_at).toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* Video / Render section */}
      {preview?.video && (
        <div style={cardStyle} data-testid="review-video-section">
          <div style={headerStyle}>
            <h3 style={sectionTitle}>Rendered Video</h3>
            <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
          </div>
          <video
            controls
            style={{
              width: "100%",
              maxHeight: 640,
              borderRadius: 6,
              background: "#000",
              marginBottom: 8,
            }}
            src={artifactUrl(preview.video.path)}
          />
          <div style={{ fontSize: 13 }}>
            <div><strong>Profile:</strong> {preview.video.render_profile ?? "default"}</div>
            <div style={metaStyle}>Created: {new Date(preview.video.created_at).toLocaleString()}</div>
          </div>
        </div>
      )}

      {/* No content message for very early stages */}
      {!script && scenes.length === 0 && Object.keys(assets).length === 0 && !preview && (
        <div
          data-testid="review-empty"
          style={{
            textAlign: "center",
            padding: 32,
            background: "#f9fafb",
            borderRadius: 8,
            border: "1px dashed #d1d5db",
            color: "#6b7280",
          }}
        >
          <p style={{ margin: "0 0 8px", fontWeight: 600 }}>No outputs yet</p>
          <p style={{ margin: 0, fontSize: 13 }}>
            This run hasn't generated any content to review.{" "}
            <Link to={editUrl} style={{ color: "#4285f4" }}>Go to editor</Link>
          </p>
        </div>
      )}

      {/* Back to editor CTA */}
      <div style={{ textAlign: "center", marginTop: 24 }}>
        <Link
          to={editUrl}
          style={{
            display: "inline-block",
            padding: "10px 24px",
            background: "#4285f4",
            color: "#fff",
            borderRadius: 6,
            textDecoration: "none",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          Back to Editor
        </Link>
      </div>
    </div>
  );
}
