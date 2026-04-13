import { useState, useEffect, useCallback } from "react";

import PipelineOverviewBar from "./PipelineOverviewBar";
import BulkActionBar from "./BulkActionBar";
import SceneCardGrid from "./SceneCardGrid";
import { useVisualPlanManager } from "./useVisualPlanManager";
import { useMediaActions } from "./useMediaActions";
import type { StoryboardResponse } from "../../api/storyboard";
import { fetchStoryboard } from "../../api/storyboard";

export interface UnifiedSceneWorkspaceProps {
  runId: number;
  currentStage: string;
  /** Increment to force immediate storyboard reload (e.g. after script edit). */
  refreshTrigger?: number;
  ttsModel?: string;
  subtitleModel?: string;
  imageModel?: string;
  pollInterval?: number;
  onStatusMessage?: (msg: string) => void;
  onRender?: () => void;
  rendering?: boolean;
  stageActionLoading?: boolean;
  onGenerateVisualPlan?: () => void;
  onApproveVisualPlan?: () => void;
  onRegenerateVisualPlan?: () => void;
}

const containerStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 12 };

const skeletonStyle: React.CSSProperties = { display: "flex", flexDirection: "column", gap: 12 };

const skeletonCardStyle: React.CSSProperties = {
  height: 100,
  borderRadius: 8,
  background: "linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%)",
  backgroundSize: "200% 100%",
  animation: "assetSlotShimmer 1.5s ease-in-out infinite",
};

const errorStyle: React.CSSProperties = { padding: "12px 16px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 6, color: "#b91c1c", fontSize: 13 };

const retryButtonStyle: React.CSSProperties = { marginLeft: 12, padding: "2px 10px", fontSize: 12, border: "1px solid #fca5a5", borderRadius: 4, background: "#fff", cursor: "pointer", color: "#b91c1c" };

const visualPlanInfoStyle: React.CSSProperties = { padding: "10px 14px", borderRadius: 8, border: "1px solid #bfdbfe", background: "#eff6ff", color: "#1e3a8a", fontSize: 13 };

const visualErrorStyle: React.CSSProperties = { padding: "8px 12px", borderRadius: 6, border: "1px solid #fecaca", background: "#fef2f2", color: "#b91c1c", fontSize: 12 };

const emptyStyle: React.CSSProperties = { textAlign: "center", padding: 28, background: "#f9fafb", borderRadius: 8, border: "1px dashed #cbd5e1", color: "#64748b", fontSize: 13 };

const GENERATING_STAGES = new Set([
  "SCRIPT_GENERATING",
  "VISUAL_PLAN_GENERATING",
  "VISUAL_ASSET_GENERATING",
  "AUDIO_GENERATING",
  "SUBTITLE_GENERATING",
  "RENDER_GENERATING",
]);

const SKELETON_KEYS = ["a", "b", "c", "d", "e", "f"];

export default function UnifiedSceneWorkspace({
  runId,
  currentStage,
  ttsModel,
  subtitleModel,
  imageModel,
  pollInterval = 4000,
  onStatusMessage,
  onRender,
  rendering = false,
  stageActionLoading = false,
  onGenerateVisualPlan,
  onApproveVisualPlan,
  onRegenerateVisualPlan,
  refreshTrigger = 0,
}: UnifiedSceneWorkspaceProps) {
  const [storyboard, setStoryboard] = useState<StoryboardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const relayStatusMessage = useCallback(
    (msg: string | null) => {
      if (msg) onStatusMessage?.(msg);
    },
    [onStatusMessage],
  );

  const { visualFieldBySceneId, onFieldChange, onSaveScene, refreshVisualPlan, visualError } =
    useVisualPlanManager(runId, currentStage, relayStatusMessage);
  const { onGenerateImage, onGenerateAudio, onGenerateSubtitles, onBulkImages, onBulkAudio, onBulkSubtitles, bulkGenerating } = useMediaActions({
    runId,
    imageModel,
    ttsModel,
    subtitleModel,
    storyboard,
    setStoryboard,
    onStatusMessage: relayStatusMessage,
  });

  const hasGeneratingParagraph =
    storyboard?.paragraphs.some((p) => p.status.startsWith("generating_")) ?? false;

  const loadStoryboard = useCallback(async () => {
    try {
      const data = await fetchStoryboard(runId);
      setStoryboard(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load storyboard");
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    void loadStoryboard();
  }, [loadStoryboard]);

  useEffect(() => {
    if (refreshTrigger > 0) {
      void loadStoryboard();
    }
  }, [refreshTrigger, loadStoryboard]);

  useEffect(() => {
    if (!hasGeneratingParagraph && !bulkGenerating && !GENERATING_STAGES.has(currentStage)) return;
    const timer = setInterval(() => {
      void loadStoryboard();
      void refreshVisualPlan();
    }, pollInterval);
    return () => clearInterval(timer);
  }, [
    hasGeneratingParagraph,
    bulkGenerating,
    currentStage,
    pollInterval,
    loadStoryboard,
    refreshVisualPlan,
  ]);

  if (loading) {
    return (
      <div style={containerStyle} data-testid="unified-scene-workspace-loading">
        <div style={skeletonStyle}>
          {SKELETON_KEYS.map((key) => (
            <div key={key} style={skeletonCardStyle} />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return <div role="alert" data-testid="unified-scene-workspace-error" style={errorStyle}>{error}<button type="button" onClick={loadStoryboard} style={retryButtonStyle}>Retry</button></div>;
  }

  if (!storyboard) return null;

  const paragraphs = storyboard.paragraphs;
  const canShowSceneGrid = currentStage !== "IDEA_READY" && currentStage !== "SCRIPT_GENERATING" && paragraphs.length > 0;
  const showVisualPlanInfo = currentStage === "VISUAL_PLAN_SETUP" || currentStage === "VISUAL_PLAN_GENERATING";

  return (
    <div style={containerStyle} data-testid="unified-scene-workspace">
      {showVisualPlanInfo && (
        <div data-testid="visual-plan-stage-info" style={visualPlanInfoStyle}>
          {currentStage === "VISUAL_PLAN_GENERATING"
            ? "Generating visual plan. Scene prompts will populate in this same grid."
            : "Visual plan setup is ready. Generate the visual plan to unlock per-scene image drafting details."}
        </div>
      )}

      {visualError && (
        <div role="alert" data-testid="visual-plan-inline-error" style={visualErrorStyle}>
          {visualError}
        </div>
      )}

      {(canShowSceneGrid || showVisualPlanInfo) && (
        <>
          <PipelineOverviewBar
            paragraphs={paragraphs}
            totalParagraphs={storyboard.total_paragraphs}
            readyParagraphs={storyboard.ready_paragraphs}
            renderReady={storyboard.render_ready}
            onRender={onRender}
            rendering={rendering}
          />

          <BulkActionBar
            currentStage={currentStage}
            paragraphs={paragraphs}
            generating={bulkGenerating}
            stageActionLoading={stageActionLoading}
            onGenerateVisualPlan={onGenerateVisualPlan}
            onApproveVisualPlan={onApproveVisualPlan}
            onRegenerateVisualPlan={onRegenerateVisualPlan}
            onGenerateAllImages={onBulkImages}
            onGenerateAllAudio={onBulkAudio}
            onGenerateAllSubtitles={onBulkSubtitles}
          />
        </>
      )}

      {canShowSceneGrid ? (
        <SceneCardGrid
          paragraphs={paragraphs}
          currentStage={currentStage}
          visualFieldBySceneId={visualFieldBySceneId}
          onVisualFieldChange={onFieldChange}
          onSaveVisualFields={onSaveScene}
          onGenerateImage={onGenerateImage}
          onGenerateAudio={(sectionId) => onGenerateAudio(sectionId)}
          onGenerateSubtitles={(sectionId) => onGenerateSubtitles(sectionId)}
          disabled={bulkGenerating || stageActionLoading}
        />
      ) : (
        <div data-testid="unified-scene-workspace-empty" style={emptyStyle}>
          No script scenes yet. Generate or finish script drafting to populate this workspace.
        </div>
      )}
    </div>
  );
}
