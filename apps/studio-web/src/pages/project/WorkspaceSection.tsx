import { Link } from "react-router-dom";

import UnifiedSceneWorkspace from "../../components/creator/UnifiedSceneWorkspace";

import type { ModelDefaults, RunDetail } from "./types";

interface WorkspaceSectionProps {
  run: RunDetail;
  currentStage: string;
  refreshTrigger: number;
  modelSelection: ModelDefaults;
  onStatusMessage: (message: string) => void;
  onRender: () => void;
  rendering: boolean;
  stageActionLoading: boolean;
  onGenerateVisualPlan: () => void;
  onApproveVisualPlan: () => void;
  onRegenerateVisualPlan: () => void;
  isFinalReview: boolean;
  previewVideoPath: string | null;
  showGoBack: boolean;
  onGoBack: () => void;
  goingBack: boolean;
  goBackLabel: string;
}

export default function WorkspaceSection({
  run,
  currentStage,
  refreshTrigger,
  modelSelection,
  onStatusMessage,
  onRender,
  rendering,
  stageActionLoading,
  onGenerateVisualPlan,
  onApproveVisualPlan,
  onRegenerateVisualPlan,
  isFinalReview,
  previewVideoPath,
  showGoBack,
  onGoBack,
  goingBack,
  goBackLabel,
}: WorkspaceSectionProps) {
  return (
    <>
      <div style={{ marginBottom: 24 }}>
        <UnifiedSceneWorkspace
          runId={run.id}
          currentStage={currentStage}
          refreshTrigger={refreshTrigger}
          ttsModel={modelSelection.tts_model}
          subtitleModel={modelSelection.subtitle_model}
          imageModel={modelSelection.image_model}
          onStatusMessage={onStatusMessage}
          onRender={onRender}
          rendering={rendering}
          stageActionLoading={stageActionLoading}
          onGenerateVisualPlan={onGenerateVisualPlan}
          onApproveVisualPlan={onApproveVisualPlan}
          onRegenerateVisualPlan={onRegenerateVisualPlan}
        />

        {isFinalReview && (
          <div
            data-testid="final-review-section"
            style={{
              textAlign: "center",
              padding: 24,
              marginTop: 16,
              background: "#f0fdf4",
              borderRadius: 8,
              border: "1px solid #bbf7d0",
              color: "#166534",
            }}
          >
            <p
              style={{
                margin: "0 0 8px",
                fontWeight: 600,
                fontSize: 16,
              }}
            >
              Pipeline Complete
            </p>
            <p style={{ margin: "0 0 16px", fontSize: 13 }}>
              All stages are done. Review the final output or restart from any stage.
            </p>
            {typeof previewVideoPath === "string" && (
              <p
                style={{
                  margin: "0 0 8px",
                  fontSize: 13,
                  color: "#374151",
                }}
              >
                Video: {previewVideoPath}
              </p>
            )}
            <Link
              to={`/review/${run.id}`}
              data-testid="review-link"
              style={{
                display: "inline-block",
                padding: "8px 24px",
                background: "#166534",
                color: "#fff",
                borderRadius: 6,
                textDecoration: "none",
                fontWeight: 600,
                fontSize: 14,
              }}
            >
              Open Review Page →
            </Link>
          </div>
        )}
      </div>

      {showGoBack && (
        <div
          style={{
            display: "flex",
            justifyContent: "flex-start",
            padding: "8px 0",
          }}
        >
          <button
            type="button"
            data-testid="go-back-btn"
            disabled={goingBack}
            onClick={onGoBack}
            style={{
              padding: "6px 16px",
              fontSize: 13,
              fontWeight: 500,
              border: "1px solid #d1d5db",
              borderRadius: 6,
              background: "#fff",
              color: "#374151",
              cursor: goingBack ? "not-allowed" : "pointer",
              opacity: goingBack ? 0.6 : 1,
            }}
          >
            {goingBack ? "Going back…" : goBackLabel}
          </button>
        </div>
      )}
    </>
  );
}
