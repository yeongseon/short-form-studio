import { Link } from "react-router-dom";
import StoryboardView from "../../components/creator/StoryboardView";
import { cardStyle, headerStyle, sectionTitle, editLinkStyle, metaStyle, previewBoxStyle } from "./reviewStyles";
import { POST_AUDIO_STAGES, type ScriptData, type LegacyVisualPlanScene, type ReviewAssets } from "./useReviewData";
import type { RunDetail } from "../../types/api";
import { visualAssetUrl } from "../../api/mediaUrls";

export function LegacyReviewSections({ run, script, scenes, assets }: {
  readonly run: RunDetail;
  readonly script: ScriptData | null;
  readonly scenes: readonly LegacyVisualPlanScene[];
  readonly assets: ReviewAssets;
}) {
  const editUrl = `/projects/${run.project_id}`;
  return <>
    {script && <div style={cardStyle} data-testid="review-script-section">
      <div style={headerStyle}>
        <h3 style={sectionTitle}>Script</h3>
        <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
      </div>
      <div style={previewBoxStyle}>{script.script ?? "(No script content)"}</div>
    </div>}
    {scenes.length > 0 && <div style={cardStyle} data-testid="review-visual-plan-section">
      <div style={headerStyle}>
        <h3 style={sectionTitle}>Visual Plan ({scenes.length} scenes)</h3>
        <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {scenes.map((scene) => <div key={scene.scene_id}
          style={{ padding: 12, background: "#f9fafb", borderRadius: 6, border: "1px solid #e5e7eb" }}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{scene.scene_id}</div>
          <div style={{ fontSize: 13, color: "#374151", marginBottom: 4 }}>{scene.original_text || scene.description || ""}</div>
          <div style={metaStyle}>Prompt: {scene.prompt || scene.image_prompt || ""}</div>
        </div>)}
      </div>
    </div>}
    {Object.keys(assets).length > 0 && <div style={cardStyle} data-testid="review-assets-section">
      <div style={headerStyle}>
        <h3 style={sectionTitle}>Visual Assets</h3>
        <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {Object.entries(assets).map(([sceneId, sceneAssets]) => <div key={sceneId}>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 8 }}>{sceneId}</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
            {sceneAssets.map((asset, idx) => <div key={asset.asset_path}
              style={{ background: asset.is_active ? "#f0fdf4" : "#f9fafb", borderRadius: 6, border: asset.is_active ? "1px solid #bbf7d0" : "1px solid #e5e7eb", overflow: "hidden" }}>
              <img src={visualAssetUrl(run.id, asset.id)} alt={`${sceneId} asset ${idx + 1}`}
                style={{ width: "100%", aspectRatio: "9 / 16", objectFit: "cover", display: "block", background: "#e5e7eb" }} />
              <div style={{ padding: "6px 8px" }}>
                <div style={{ fontSize: 11, color: "#374151", wordBreak: "break-all" }}>{asset.asset_path.split("/").pop()}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 2 }}>
                  <span style={metaStyle}>Model: {asset.model_used}</span>
                  {asset.is_active && <span style={{ fontSize: 10, color: "#166534", fontWeight: 600, background: "#dcfce7", padding: "1px 5px", borderRadius: 3 }}>ACTIVE</span>}
                </div>
              </div>
            </div>)}
          </div>
        </div>)}
      </div>
    </div>}
    {POST_AUDIO_STAGES.has(run.current_stage) && <div style={cardStyle} data-testid="review-storyboard-section">
      <div style={headerStyle}>
        <h3 style={sectionTitle}>Storyboard (Audio &amp; Subtitles)</h3>
        <Link to={editUrl} style={editLinkStyle}>Edit in Project &rarr;</Link>
      </div>
      <StoryboardView runId={run.id} readOnly />
    </div>}
  </>;
}
