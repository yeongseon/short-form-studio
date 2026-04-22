import ScriptComposer from "../../components/creator/ScriptComposer";

type SourceType = "idea" | "markdown" | "json" | "pasted_json" | "url";

interface ScriptSectionProps {
  runId: number;
  currentStage: string;
  sourceType: SourceType;
  selectedScriptModel?: string;
  onModelChange: (category: string, modelKey: string) => void;
  onConfirm: () => void;
  onGenerate: () => void;
  onRegenerate: () => void;
  onScriptChange: () => void;
  onStatusMessage: (message: string) => void;
  disabled: boolean;
}

export default function ScriptSection({
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
  disabled,
}: ScriptSectionProps) {
  return (
    <div style={{ marginBottom: 24 }}>
      <ScriptComposer
        runId={runId}
        currentStage={currentStage}
        sourceType={sourceType}
        selectedScriptModel={selectedScriptModel}
        onModelChange={onModelChange}
        onConfirm={onConfirm}
        onGenerate={onGenerate}
        onRegenerate={onRegenerate}
        onScriptChange={onScriptChange}
        onStatusMessage={onStatusMessage}
        disabled={disabled}
      />
    </div>
  );
}
