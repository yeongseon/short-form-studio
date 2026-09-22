import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiVoid, API_BASE } from "../../api/client";
import { runArtifactUrl, type RenderedVideo } from "../../api/runPreview";
import type { RunDetail } from "../../types/api";
import Button from "../../components/ui/Button";
import { cardStyle, headerStyle, sectionTitle, editLinkStyle, metaStyle } from "./reviewStyles";

export function RenderedVideoReview({ run, video, onPublished }: {
  readonly run: RunDetail;
  readonly video: RenderedVideo;
  readonly onPublished: () => Promise<void>;
}) {
  const lock = useRef(false);
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mediaError, setMediaError] = useState(false);
  const publish = async () => {
    if (lock.current || run.current_stage !== "FINAL_REVIEW") return;
    lock.current = true;
    setPublishing(true);
    setError(null);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/approve-final`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer: "studio-user" }),
      });
      await onPublished();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not publish. Reload the review to check its status.");
    } finally {
      lock.current = false;
      setPublishing(false);
    }
  };
  const url = runArtifactUrl(run.id, video.id);
  return <div style={cardStyle} data-testid="review-video-section">
    <div style={headerStyle}>
      <h3 style={sectionTitle}>Rendered Video</h3>
      <Link to={`/projects/${run.project_id}`} style={editLinkStyle}>Edit in Project &rarr;</Link>
    </div>
    <video key={url} controls playsInline src={url} onError={() => setMediaError(true)} onLoadedData={() => setMediaError(false)}
      style={{ width: "100%", maxHeight: 640, borderRadius: 6, background: "#000", marginBottom: 8 }}>
      <track kind="captions" />
    </video>
    {mediaError && <p role="alert">Video could not play. Download the video to review it, or reload to retry playback.</p>}
    <div style={{ fontSize: 13 }}>
      <div><strong>Profile:</strong> {video.render_profile ?? "default"}</div>
      <div style={metaStyle}>Created: {new Date(video.created_at).toLocaleString()}</div>
    </div>
    <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginTop: 12 }}>
      <a href={url} download={`run-${run.id}.mp4`} style={editLinkStyle}>Download video</a>
      {run.current_stage === "FINAL_REVIEW" && <Button disabled={publishing} onClick={publish}>
        {publishing ? "Publishing…" : "Approve final & publish"}
      </Button>}
      {run.current_stage === "PUBLISHED" && <span role="status">Published</span>}
    </div>
    {error && <p role="alert">{error}</p>}
  </div>;
}
