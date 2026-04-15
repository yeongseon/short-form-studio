import { Link, useNavigate, useParams } from "react-router-dom";

import ProjectHeader from "./project/ProjectHeader";
import ScriptSection from "./project/ScriptSection";
import { FINAL_REVIEW_STAGES, STAGE_BACK_LABELS } from "./project/types";
import { useProjectData } from "./project/useProjectData";
import { useRunActions } from "./project/useRunActions";
import WorkspaceSection from "./project/WorkspaceSection";

type SourceType = "idea" | "markdown" | "json" | "pasted_json" | "url";

export default function ProjectPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const numericProjectId = Number(projectId);
  const navigate = useNavigate();

  const {
    project,
    setProject,
    run,
    loading,
    error,
    preview,
    modelSelection,
    onModelChange,
    refreshRun,
  } = useProjectData(numericProjectId);

  const {
    handleTitleSave,
    handleGoBack,
    handleApprove,
    handleGenerate,
    handleRestart,
    handleApproveVisualPlan,
    handleGenerateVisualPlan,
    handleRestartVisualPlan,
    handleRender,
    handleStop,
    handleResume,
    handleDeleteProject,
    approving,
    generating,
    restarting,
    stopping,
    resuming,
    deleting,
    savingTitle,
    goingBack,
    statusMessage,
    setStatusMessage,
    confirmAction,
    setConfirmAction,
    titleDraft,
    setTitleDraft,
    scriptVersion,
    setScriptVersion,
  } = useRunActions({
    run,
    project,
    numericProjectId,
    modelSelection,
    setProject,
    refreshRun,
    navigate,
  });

  const currentStage = run?.current_stage ?? "IDEA_READY";
  const isFailed = run?.status === "failed";
  const showScriptComposer = true;
  const isFinalReview = FINAL_REVIEW_STAGES.has(currentStage);
  const previewVideo = (preview as Record<string, unknown> | null)?.video;
  const previewVideoPath =
    previewVideo && typeof previewVideo === "object"
      ? (previewVideo as Record<string, unknown>).path
      : null;
  const maxWidth = run ? 1200 : 960;
  const showGoBack =
    Boolean(run) &&
    Boolean(STAGE_BACK_LABELS[currentStage]) &&
    !(currentStage === "SCRIPT_REVIEW" && project?.source_type !== "idea");

  if (Number.isNaN(numericProjectId)) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p style={{ color: "#b91c1c" }}>Invalid project ID.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>
          Back to projects
        </Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div
        role="status"
        aria-label="Loading project"
        style={{
          maxWidth: 720,
          margin: "0 auto",
          padding: 24,
          textAlign: "center",
          color: "#6b7280",
        }}
      >
        Loading project…
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
        <Link to="/runs" style={{ color: "#4285f4", fontSize: 13 }}>
          Back to projects
        </Link>
      </div>
    );
  }

  if (!project) {
    return (
      <div style={{ maxWidth: 720, margin: "0 auto", padding: 24 }}>
        <p>Project not found.</p>
        <Link to="/runs" style={{ color: "#4285f4" }}>
          Back to projects
        </Link>
      </div>
    );
  }

  void isFailed;

  return (
    <div style={{ maxWidth, margin: "0 auto", padding: 24 }}>
      <ProjectHeader
        project={project}
        run={run}
        titleDraft={titleDraft}
        setTitleDraft={setTitleDraft}
        savingTitle={savingTitle}
        onTitleSave={handleTitleSave}
        stopping={stopping}
        resuming={resuming}
        deleting={deleting}
        confirmAction={confirmAction}
        setConfirmAction={setConfirmAction}
        onStop={handleStop}
        onResume={handleResume}
        onDelete={handleDeleteProject}
        onNavigateBack={() => navigate("/runs")}
        currentStage={currentStage}
      />

      {!run && (
        <div
          data-testid="no-run"
          style={{
            textAlign: "center",
            padding: 32,
            background: "#f9fafb",
            borderRadius: 8,
            border: "1px dashed #d1d5db",
            color: "#6b7280",
            marginBottom: 24,
          }}
        >
          <p style={{ margin: "0 0 8px", fontWeight: 600 }}>No runs yet</p>
          <p style={{ margin: 0, fontSize: 13 }}>
            This project has no pipeline runs. Go back to create a new one.
          </p>
        </div>
      )}

      {run && showScriptComposer && (
        <ScriptSection
          runId={run.id}
          currentStage={currentStage}
          sourceType={project.source_type as SourceType}
          selectedScriptModel={modelSelection.script_model}
          onModelChange={onModelChange}
          onConfirm={handleApprove}
          onGenerate={handleGenerate}
          onRegenerate={handleRestart}
          onScriptChange={() => setScriptVersion((v) => v + 1)}
          onStatusMessage={(message) => setStatusMessage(message)}
          disabled={approving || generating || restarting}
        />
      )}

      {run && (
        <WorkspaceSection
          run={run}
          currentStage={currentStage}
          refreshTrigger={scriptVersion}
          modelSelection={modelSelection}
          onStatusMessage={(message) => setStatusMessage(message)}
          onRender={handleRender}
          rendering={generating}
          stageActionLoading={approving || generating || restarting}
          onGenerateVisualPlan={handleGenerateVisualPlan}
          onApproveVisualPlan={handleApproveVisualPlan}
          onRegenerateVisualPlan={handleRestartVisualPlan}
          isFinalReview={isFinalReview}
          previewVideoPath={typeof previewVideoPath === "string" ? previewVideoPath : null}
          showGoBack={showGoBack}
          onGoBack={handleGoBack}
          goingBack={goingBack}
          goBackLabel={STAGE_BACK_LABELS[currentStage]}
        />
      )}

      {statusMessage && (
        <div
          data-testid="status-toast"
          style={{
            position: "fixed",
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "10px 24px",
            background: "#1f2937",
            color: "#fff",
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 500,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: 1000,
          }}
        >
          {statusMessage}
        </div>
      )}
    </div>
  );
}
