import ConfirmDialog from "../../components/creator/ConfirmDialog";

import type { ProjectDetail, RunDetail } from "./types";

interface ProjectHeaderProps {
  project: ProjectDetail;
  run: RunDetail | null;
  titleDraft: string;
  setTitleDraft: React.Dispatch<React.SetStateAction<string>>;
  savingTitle: boolean;
  onTitleSave: () => Promise<void>;
  stopping: boolean;
  resuming: boolean;
  deleting: boolean;
  confirmAction: "stop" | "resume" | "delete" | null;
  setConfirmAction: React.Dispatch<React.SetStateAction<"stop" | "resume" | "delete" | null>>;
  onStop: () => Promise<void>;
  onResume: () => Promise<void>;
  onDelete: () => Promise<void>;
  onNavigateBack: () => void;
  currentStage: string;
}

export default function ProjectHeader({
  project,
  run,
  titleDraft,
  setTitleDraft,
  savingTitle,
  onTitleSave,
  stopping,
  resuming,
  deleting,
  confirmAction,
  setConfirmAction,
  onStop,
  onResume,
  onDelete,
  onNavigateBack,
  currentStage,
}: ProjectHeaderProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      <button
        type="button"
        onClick={onNavigateBack}
        style={{
          color: "#6b7280",
          fontSize: 12,
          textDecoration: "none",
          border: "none",
          background: "transparent",
          padding: 0,
          cursor: "pointer",
        }}
      >
        ← Projects
      </button>
      <input
        data-testid="project-title"
        value={titleDraft}
        onChange={(e) => setTitleDraft(e.target.value)}
        onBlur={() => void onTitleSave()}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
        }}
        disabled={savingTitle}
        placeholder="Untitled Project"
        style={{
          fontSize: 22,
          fontWeight: 700,
          margin: "8px 0 4px",
          padding: "2px 8px",
          border: "1px solid transparent",
          borderRadius: 6,
          background: "transparent",
          outline: "none",
          width: "100%",
          transition: "border-color 0.15s, background 0.15s",
          cursor: "text",
        }}
        onFocus={(e) => {
          e.currentTarget.style.borderColor = "#d1d5db";
          e.currentTarget.style.background = "#fff";
        }}
        onMouseEnter={(e) => {
          if (document.activeElement !== e.currentTarget) {
            e.currentTarget.style.borderColor = "#e5e7eb";
          }
        }}
        onMouseLeave={(e) => {
          if (document.activeElement !== e.currentTarget) {
            e.currentTarget.style.borderColor = "transparent";
            e.currentTarget.style.background = "transparent";
          }
        }}
      />
      <span style={{ fontSize: 12, color: "#6b7280" }}>
        Source: {project.source_type} · Status: {run ? run.status : project.status}
        {run ? ` · Stage: ${currentStage}` : ""}
      </span>

      <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
        {run && run.status === "running" && (
          <button
            type="button"
            onClick={() => setConfirmAction("stop")}
            disabled={stopping}
            style={{
              padding: "6px 14px",
              border: "1px solid #dc2626",
              borderRadius: 6,
              background: "#fff",
              color: "#dc2626",
              fontSize: 12,
              fontWeight: 600,
              cursor: stopping ? "not-allowed" : "pointer",
            }}
          >
            {stopping ? "Stopping…" : "⏹ Stop"}
          </button>
        )}
        {run &&
          (run.status === "cancelled" || run.status === "failed" || run.status === "paused") && (
            <button
              type="button"
              onClick={() => setConfirmAction("resume")}
              disabled={resuming}
              style={{
                padding: "6px 14px",
                border: "1px solid #16a34a",
                borderRadius: 6,
                background: "#fff",
                color: "#16a34a",
                fontSize: 12,
                fontWeight: 600,
                cursor: resuming ? "not-allowed" : "pointer",
              }}
            >
              {resuming ? "Resuming…" : "▶ Resume"}
            </button>
          )}
        <button
          type="button"
          onClick={() => setConfirmAction("delete")}
          disabled={deleting}
          style={{
            padding: "6px 14px",
            border: "1px solid #dc2626",
            borderRadius: 6,
            background: "#fff",
            color: "#dc2626",
            fontSize: 12,
            fontWeight: 600,
            cursor: deleting ? "not-allowed" : "pointer",
          }}
        >
          {deleting ? "Deleting…" : "🗑 Delete Project"}
        </button>
      </div>

      <ConfirmDialog
        open={confirmAction !== null}
        title={
          confirmAction === "stop"
            ? "Stop Run?"
            : confirmAction === "resume"
              ? "Resume Run?"
              : "Delete Project?"
        }
        message={
          confirmAction === "stop"
            ? "This will cancel the current generation task and stop the pipeline run."
            : confirmAction === "resume"
              ? "This will resume the stopped/failed run from where it left off."
              : "This will permanently delete the project and all its runs, assets, and generated content. This action cannot be undone."
        }
        variant={
          confirmAction === "stop"
            ? "warning"
            : confirmAction === "resume"
              ? "info"
              : "danger"
        }
        confirmLabel={
          confirmAction === "stop"
            ? "Stop Run"
            : confirmAction === "resume"
              ? "Resume"
              : "Delete Forever"
        }
        loading={stopping || resuming || deleting}
        onConfirm={async () => {
          if (confirmAction === "stop") await onStop();
          else if (confirmAction === "resume") await onResume();
          else if (confirmAction === "delete") await onDelete();
          setConfirmAction(null);
        }}
        onCancel={() => setConfirmAction(null)}
      />
    </div>
  );
}
