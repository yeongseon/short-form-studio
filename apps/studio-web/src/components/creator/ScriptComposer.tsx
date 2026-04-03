/**
 * ScriptComposer — always-visible JSON editor + action buttons.
 *
 * Shows the JsonScriptEditor (single source of truth).
 * Structured metadata is shown in SceneCards below, not here.
 * When the user saves JSON, the backend parses it into sections
 * and onScriptChange fires so the parent can refresh downstream
 * data (storyboard).
 */

import JsonScriptEditor from "./JsonScriptEditor";
import ModelSelector from "./ModelSelector";

// --------------- types ---------------

export interface ScriptComposerProps {
  runId: number;
  /** Current backend stage. */
  currentStage: string;
  /** Source type from the project. */
  sourceType: "idea" | "markdown" | "json" | "pasted_json" | "url";
  /** Model selection state for script category. */
  selectedScriptModel?: string;
  /** Called when model selection changes. */
  onModelChange?: (category: string, modelKey: string) => void;
  /** Called when script is approved and visual plan generation should begin. */
  onConfirm?: () => void;
  /** Called when script generation should start. */
  onGenerate?: () => void;
  /** Called when script should be regenerated. */
  onRegenerate?: () => void;
  /** Called after save completes — parent should refresh storyboard. */
  onScriptChange?: () => void;
  /** Status message callback. */
  onStatusMessage?: (msg: string) => void;
  /** Whether action buttons should be disabled (e.g. during generation). */
  disabled?: boolean;
}

// --------------- styles ---------------

const containerStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 12,
};

const actionBarStyle: React.CSSProperties = {
  display: "flex",
  gap: 8,
  padding: "10px 0",
  alignItems: "center",
};

const primaryBtnStyle: React.CSSProperties = {
  padding: "8px 20px",
  fontSize: 13,
  fontWeight: 700,
  border: "none",
  borderRadius: 6,
  background: "#4285f4",
  color: "#fff",
  cursor: "pointer",
  transition: "all 0.15s",
};

const secondaryBtnStyle: React.CSSProperties = {
  padding: "8px 16px",
  fontSize: 13,
  fontWeight: 600,
  border: "1px solid #d1d5db",
  borderRadius: 6,
  background: "#fff",
  color: "#374151",
  cursor: "pointer",
  transition: "all 0.15s",
};

// --------------- component ---------------

export default function ScriptComposer({
  runId,
  currentStage,
  sourceType,
  selectedScriptModel,
  onModelChange,
  onConfirm,
  onGenerate,
  onRegenerate,
  onScriptChange,
  onStatusMessage,
  disabled = false,
}: ScriptComposerProps) {
  const isIdeaReady = currentStage === "IDEA_READY";
  const isGenerating = currentStage === "SCRIPT_GENERATING";
  const isReview = currentStage === "SCRIPT_REVIEW";
  const isEditable = true;
  const showGenerateBtn = isIdeaReady;
  const showApproveBtn = isReview;
  const showRegenerateBtn = isReview;

  return (
    <div style={containerStyle} data-testid="script-composer">
      {/* Generating indicator */}
      {isGenerating && (
        <div
          data-testid="script-generating-indicator"
          style={{
            padding: "10px 14px",
            background: "#eff6ff",
            borderRadius: 8,
            border: "1px solid #bfdbfe",
            color: "#1e40af",
            fontSize: 13,
          }}
        >
          Generating script… Draft will update automatically.
        </div>
      )}

      {/* Model selector for script */}
      {(isIdeaReady || isReview) && sourceType !== "markdown" && sourceType !== "json" && sourceType !== "pasted_json" && onModelChange && (
        <ModelSelector
          categories={["script"]}
          selectedModels={selectedScriptModel ? { script: selectedScriptModel } : undefined}
          apiBase=""
          onSelectionChange={onModelChange}
        />
      )}

      {/* JSON editor — single source of truth */}
      <JsonScriptEditor
        runId={runId}
        readOnly={!isEditable}
        pollIntervalMs={isGenerating ? 3000 : undefined}
        suppressMissingDraftError={isIdeaReady || isGenerating}
        pendingMessage={
          isIdeaReady
            ? "No script yet. Click Generate Script to start."
            : isGenerating
              ? "Waiting for generated script\u2026"
              : undefined
        }
        onSuccess={(action) => {
          if (action === "save") {
            onStatusMessage?.("Script saved — scenes updated");
            onScriptChange?.();
          }
        }}
        onError={(_action, msg) => onStatusMessage?.(msg)}
      />

      {/* Action buttons */}
      <div style={actionBarStyle} data-testid="script-actions">
        {showGenerateBtn && (
          <button
            type="button"
            style={{
              ...primaryBtnStyle,
              opacity: disabled ? 0.5 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={onGenerate}
            disabled={disabled}
            data-testid="btn-generate-script"
          >
            Generate Script
          </button>
        )}
        {showApproveBtn && (
          <button
            type="button"
            style={{
              ...primaryBtnStyle,
              background: "#22c55e",
              opacity: disabled ? 0.5 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={onConfirm}
            disabled={disabled}
            data-testid="btn-confirm-script"
          >
            Confirm & Generate Visual Plan
          </button>
        )}
        {showRegenerateBtn && (
          <button
            type="button"
            style={{
              ...secondaryBtnStyle,
              opacity: disabled ? 0.5 : 1,
              cursor: disabled ? "not-allowed" : "pointer",
            }}
            onClick={onRegenerate}
            disabled={disabled}
            data-testid="btn-regenerate-script"
          >
            Regenerate
          </button>
        )}
      </div>
    </div>
  );
}
