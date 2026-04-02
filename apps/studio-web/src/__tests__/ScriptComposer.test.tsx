import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ScriptComposer from "../components/creator/ScriptComposer";

// Mock child editors to avoid complex setup
vi.mock("../components/creator/MarkdownScriptEditor", () => ({
  default: (props: Record<string, unknown>) => (
    <div data-testid="markdown-editor" data-readonly={String(props.readOnly)}>
      MarkdownEditor
    </div>
  ),
}));

vi.mock("../components/creator/StructuredScriptEditor", () => ({
  default: (props: Record<string, unknown>) => (
    <div data-testid="structured-editor" data-readonly={String(props.readOnly)}>
      StructuredEditor
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

  it("shows source context when provided", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
        sourceContext="A video about cats"
      />,
    );
    expect(screen.getByText("A video about cats")).toBeInTheDocument();
  });

  it("switches editor mode tabs", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
      />,
    );
    // Default is markdown
    expect(screen.getByTestId("markdown-editor")).toBeInTheDocument();
    // Click structured tab
    fireEvent.click(screen.getByText("Structured"));
    expect(screen.getByTestId("structured-editor")).toBeInTheDocument();
    // Click back to markdown
    fireEvent.click(screen.getByText("Markdown"));
    expect(screen.getByTestId("markdown-editor")).toBeInTheDocument();
  });

  it("passes readOnly=false to editor in SCRIPT_REVIEW stage", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="SCRIPT_REVIEW"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("markdown-editor")).toHaveAttribute("data-readonly", "false");
  });

  it("passes readOnly=true to editor in IDEA_READY stage", () => {
    render(
      <ScriptComposer
        runId={1}
        currentStage="IDEA_READY"
        sourceType="idea"
      />,
    );
    expect(screen.getByTestId("markdown-editor")).toHaveAttribute("data-readonly", "true");
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
});
