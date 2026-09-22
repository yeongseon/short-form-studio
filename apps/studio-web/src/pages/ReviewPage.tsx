import { Link, useParams } from "react-router-dom";
import PipelineStepper from "../components/creator/PipelineStepper";
import { TimelineWorkflow } from "../components/creator/TimelineWorkflow";
import { LegacyReviewSections } from "./review/LegacyReviewSections";
import { RenderedVideoReview } from "./review/RenderedVideoReview";
import { useReviewData } from "./review/useReviewData";

export default function ReviewPage() {
  const { runId } = useParams<{ runId: string }>();
  const numericRunId = Number(runId);
  const { run, preview, script, scenes, assets, loading, error, refreshRun } = useReviewData(numericRunId);

  if (Number.isNaN(numericRunId)) return <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
    <p style={{ color: "#b91c1c" }}>Invalid run ID.</p>
    <Link to="/runs" style={{ color: "#4285f4" }}>Back to projects</Link>
  </div>;
  if (loading) return <div role="status" aria-label="Loading review"
    style={{ maxWidth: 720, margin: "0 auto", padding: 24, textAlign: "center", color: "#6b7280" }}>Loading review...</div>;
  if (error) return <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
    <div role="alert" style={{ padding: "12px 16px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, color: "#b91c1c", fontSize: 13, marginBottom: 16 }}>{error}</div>
    <Link to="/runs" style={{ color: "#4285f4", fontSize: 13 }}>Back to projects</Link>
  </div>;
  if (!run) return <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
    <p>Run not found.</p><Link to="/runs" style={{ color: "#4285f4" }}>Back to projects</Link>
  </div>;

  const stage = run.current_stage;
  const isFailed = run.status === "failed";
  const editUrl = `/projects/${run.project_id}`;
  const timelineBacked = run.metadata?.render_source === "timeline";
  return <div style={{ maxWidth: 960, margin: "0 auto", padding: 24 }}>
    <div style={{ marginBottom: 16 }}>
      <Link to="/runs" style={{ color: "#6b7280", fontSize: 12, textDecoration: "none" }}>&larr; Projects</Link>
      <h1 style={{ fontSize: 22, fontWeight: 700, margin: "8px 0 4px" }}>Review &mdash; Run #{run.id}</h1>
      <span style={{ fontSize: 12, color: "#6b7280" }}>
        Stage: {stage} &middot; Status: {run.status}
        {isFailed && <span style={{ color: "#b91c1c", fontWeight: 600 }}> (FAILED)</span>}
      </span>
    </div>
    <div style={{ marginBottom: 24 }}>
      {timelineBacked ? <TimelineWorkflow currentStage={stage} /> : <PipelineStepper currentStage={stage} failed={isFailed} />}
    </div>
    {!timelineBacked && <LegacyReviewSections run={run} script={script} scenes={scenes} assets={assets} />}
    {preview?.video && <RenderedVideoReview key={run.id} run={run} video={preview.video} onPublished={refreshRun} />}
    {!script && scenes.length === 0 && Object.keys(assets).length === 0 && !preview && <div data-testid="review-empty"
      style={{ textAlign: "center", padding: 32, background: "#f9fafb", borderRadius: 8, border: "1px dashed #d1d5db", color: "#6b7280" }}>
      <p style={{ margin: "0 0 8px", fontWeight: 600 }}>No outputs yet</p>
      <p style={{ margin: 0, fontSize: 13 }}>This run hasn&apos;t generated any content to review.{" "}
        <Link to={editUrl} style={{ color: "#4285f4" }}>Go to editor</Link>
      </p>
    </div>}
    <div style={{ textAlign: "center", marginTop: 24 }}>
      <Link to={editUrl} style={{ display: "inline-block", padding: "10px 24px", background: "#4285f4", color: "#fff", borderRadius: 6, textDecoration: "none", fontSize: 14, fontWeight: 600 }}>Back to Editor</Link>
    </div>
  </div>;
}
