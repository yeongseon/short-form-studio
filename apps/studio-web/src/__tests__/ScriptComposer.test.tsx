import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ScriptComposer from "../components/creator/ScriptComposer";

// Mock child editors to avoid complex setup
vi.mock("../components/creator/JsonScriptEditor", () => ({
  default: (props: Record<string, unknown>) => (
    <div data-testid="json-editor" data-readonly={String(props.readOnly)}>
      JsonEditor
    </div>
  ),
}));

vi.mock("../components/creator/ModelSelector", () => ({
  default: () => <div data-testid="model-selector">ModelSelector</div>,
}));

describe("ScriptComposer", () => {
  it("renders script composer container", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("script-composer")).toBeInTheDocument();
  });

  it("shows Generate Script button in IDEA_READY stage", () => {
    const onGenerate = vi.fn();
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
        onGenerate={onGenerate}
      />,
    );
    const btn = screen.getByTestId("btn-generate-script");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it("shows Confirm and Regenerate buttons in SCRIPT_REVIEW stage", () => {
    const onConfirm = vi.fn();
    const onRegenerate = vi.fn();
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
        onConfirm={onConfirm}
        onRegenerate={onRegenerate}
      />,
    );
    expect(screen.getByTestId("btn-confirm-script")).toBeInTheDocument();
    expect(screen.getByTestId("btn-regenerate-script")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("btn-confirm-script"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("shows generating indicator during SCRIPT_GENERATING", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_GENERATING"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("script-generating-indicator")).toBeInTheDocument();
  });

  it("shows only JSON editor (no tabs, no structured editor)", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("json-editor")).toBeInTheDocument();
    // No tab buttons or structured editor
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByText("Structured")).not.toBeInTheDocument();
  });

  it("passes readOnly=false to editor — always editable", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("json-editor")).toHaveAttribute("data-readonly", "false");
  });

  it("editor is always editable regardless of stage", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("json-editor")).toHaveAttribute("data-readonly", "false");
  });

  it("disables buttons when disabled prop is true", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
        onGenerate={vi.fn()}
        disabled
      />,
    );
    expect(screen.getByTestId("btn-generate-script")).toBeDisabled();
  });

  it("hides generate button in SCRIPT_REVIEW", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
      />,
    );
    expect(screen.queryByTestId("btn-generate-script")).not.toBeInTheDocument();
  });

  it("hides confirm/regenerate in IDEA_READY", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
      />,
    );
    expect(screen.queryByTestId("btn-confirm-script")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-regenerate-script")).not.toBeInTheDocument();
  });

  it("hides script model selector for markdown source", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="markdown"
        onModelChange={vi.fn()}
      />,
    );
    expect(screen.queryByTestId("model-selector")).not.toBeInTheDocument();
  });
});
