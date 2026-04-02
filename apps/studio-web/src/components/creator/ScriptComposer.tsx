/**
 * ScriptComposer — script editing phase before scene generation.
 *
 * Wraps MarkdownScriptEditor / StructuredScriptEditor with a
 * "Confirm Script" button that triggers visual plan generation
 * and signals the parent to transition to StoryboardWorkspace.
 */

import { useState, useCallback } from "react";

import MarkdownScriptEditor from "./MarkdownScriptEditor";
import StructuredScriptEditor from "./StructuredScriptEditor";
import ModelSelector from "./ModelSelector";

const API_BASE = "/api/creator";

// --------------- types ---------------

type EditorMode = "markdown" | "structured";

export interface ScriptComposerProps {
  runId: number;
  /** Current backend stage. */
  currentStage: string;
  /** Source type from the project. */
  sourceType: "idea" | "markdown" | "url";
  /** Source context text to display. */
  sourceContext?: string | null;
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

const sourceBoxStyle: React.CSSProperties = {
  padding: "10px 14px",
  background: "#f9fafb",
  border: "1px solid #e5e7eb",
  borderRadius: 8,
  fontSize: 13,
  lineHeight: 1.5,
  color: "#374151",
  whiteSpace: "pre-wrap",
};

const tabListStyle: React.CSSProperties = {
  display: "flex",
  gap: 4,
  borderBottom: "2px solid #ddd",
};

const tabStyle = (active: boolean): React.CSSProperties => ({
  padding: "6px 14px",
  border: "none",
  borderBottom: active ? "2px solid #4285f4" : "2px solid transparent",
  background: "transparent",
  cursor: "pointer",
  fontWeight: active ? 600 : 400,
  color: active ? "#4285f4" : "#666",
  fontSize: 13,
});

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
  sourceContext,
  selectedScriptModel,
  onModelChange,
  onConfirm,
  onGenerate,
  onRegenerate,
  onStatusMessage,
  disabled = false,
}: ScriptComposerProps) {
  const [editorMode, setEditorMode] = useState<EditorMode>("markdown");

  const isIdeaReady = currentStage === "IDEA_READY";
  const isGenerating = currentStage === "SCRIPT_GENERATING";
  const isReview = currentStage === "SCRIPT_REVIEW";
  const isEditable = isReview;
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

      {/* Source context */}
      {sourceContext && (
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 4 }}>
            Source ({sourceType})
          </div>
          <div style={sourceBoxStyle}>{sourceContext}</div>
        </div>
      )}

      {/* Model selector for script */}
      {(isIdeaReady || isReview) && onModelChange && (
        <ModelSelector
          categories={["script"]}
          selectedModels={selectedScriptModel ? { script: selectedScriptModel } : undefined}
          apiBase=""
          onSelectionChange={onModelChange}
        />
      )}

      {/* Editor mode tabs */}
      <div role="tablist" style={tabListStyle}>
        <button
          type="button"
          role="tab"
          id="tab-md"
          aria-selected={editorMode === "markdown"}
          aria-controls="panel-md"
          onClick={() => setEditorMode("markdown")}
          style={tabStyle(editorMode === "markdown")}
        >
          Markdown
        </button>
        <button
          type="button"
          role="tab"
          id="tab-struct"
          aria-selected={editorMode === "structured"}
          aria-controls="panel-struct"
          onClick={() => setEditorMode("structured")}
          style={tabStyle(editorMode === "structured")}
        >
          Structured
        </button>
      </div>

      {/* Editor panels */}
      {editorMode === "markdown" && (
        <div role="tabpanel" id="panel-md" aria-labelledby="tab-md">
          <MarkdownScriptEditor
            runId={runId}
            readOnly={!isEditable}
            pollIntervalMs={isIdeaReady || isGenerating ? 3000 : undefined}
            suppressMissingDraftError={isIdeaReady || isGenerating}
            pendingMessage={
              isIdeaReady
                ? "No script yet. Click Generate Script to start."
                : "Waiting for generated script…"
            }
            onSuccess={() => onStatusMessage?.("Script saved")}
            onError={(_action, msg) => onStatusMessage?.(msg)}
          />
        </div>
      )}
      {editorMode === "structured" && (
        <div role="tabpanel" id="panel-struct" aria-labelledby="tab-struct">
          <StructuredScriptEditor
            runId={runId}
            readOnly={!isEditable}
            pollIntervalMs={isIdeaReady || isGenerating ? 3000 : undefined}
            suppressMissingDraftError={isIdeaReady || isGenerating}
            pendingMessage={
              isIdeaReady
                ? "No structured sections yet. Generate a script first."
                : "Waiting for generated sections…"
            }
            onSuccess={() => onStatusMessage?.("Script saved")}
            onError={(_action, msg) => onStatusMessage?.(msg)}
          />
        </div>
      )}

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
