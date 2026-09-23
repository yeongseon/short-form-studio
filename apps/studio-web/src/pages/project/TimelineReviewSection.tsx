import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { apiVoid, API_BASE } from "../../api/client";
import TimelinePreview from "../../components/creator/TimelinePreview";
import ProgressDialog from "../../components/creator/ProgressDialog";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import type { RunDetail } from "./types";

export function TimelineReviewSection({ run, refreshRun }: {
  readonly run: RunDetail;
  readonly refreshRun: (id: number) => Promise<void>;
}) {
  const [revision, setRevision] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [approving, setApproving] = useState(false);
  const [progress, setProgress] = useState(false);
  const lock = useRef(false);
  const onReady = useCallback((previewRevision: unknown) => {
    if (typeof previewRevision === "number" && Number.isSafeInteger(previewRevision) && previewRevision >= 0) {
      setRevision(previewRevision);
    } else {
      setRevision(null);
      setError("Preview revision is missing or invalid. Reload the project before approving.");
    }
  }, []);
  const onUnavailable = useCallback(() => setRevision(null), []);
  const onComplete = useCallback(() => { void refreshRun(run.id); }, [refreshRun, run.id]);

  const approve = async () => {
    if (lock.current || revision === null || run.current_stage !== "TIMELINE_REVIEW") return;
    lock.current = true;
    setApproving(true);
    setError(null);
    try {
      await apiVoid(`${API_BASE}/runs/${run.id}/approve-timeline-render`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: revision }),
      });
      setProgress(true);
      await refreshRun(run.id);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not approve timeline.");
    } finally {
      lock.current = false;
      setApproving(false);
    }
  };

  return <Card style={{ marginBottom: 24 }}>
    <h2>Saved Timeline preview</h2>
    {revision !== null && <p>Revision {revision}. Review this saved timeline before approving the render.</p>}
    <TimelinePreview projectId={run.project_id} onReady={onReady} onUnavailable={onUnavailable} />
    {error && <p role="alert">{error}</p>}
    {run.error_message && <p role="alert">{run.error_message}</p>}
    {run.current_stage === "TIMELINE_REVIEW" && <Button
      disabled={revision === null || approving} onClick={approve}>
      {approving ? "Approving…" : "Approve timeline & render"}
    </Button>}
    {run.current_stage === "RENDER_GENERATING" && <Button onClick={() => setProgress(true)}>View render progress</Button>}
    {(run.current_stage === "FINAL_REVIEW" || run.current_stage === "PUBLISHED") && <div data-testid="final-review-section">
      <p>{run.current_stage === "PUBLISHED" ? "Published" : "Render complete — review the final output."}</p>
      <Link to={`/review/${run.id}`} data-testid="review-link">Open Review Page →</Link>
    </div>}
    <ProgressDialog open={progress} runId={run.id} expectedStage="RENDER_GENERATING"
      onComplete={onComplete} onFailed={onComplete} onClose={() => setProgress(false)} />
  </Card>;
}
