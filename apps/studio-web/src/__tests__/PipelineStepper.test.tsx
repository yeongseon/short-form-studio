import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import PipelineStepper, {
  PIPELINE_STEPS,
  STAGE_TO_STEP,
} from "../components/creator/PipelineStepper";

describe("PipelineStepper", () => {
  it("renders all 6 pipeline steps", () => {
    render(<PipelineStepper currentStage="IDEA_READY" />);
    const stepper = screen.getByTestId("pipeline-stepper");
    expect(stepper).toBeInTheDocument();
    for (const step of PIPELINE_STEPS) {
      expect(screen.getByTestId(`step-${step.key}`)).toBeInTheDocument();
    }
  });

  it("marks the first step as current for IDEA_READY", () => {
    render(<PipelineStepper currentStage="IDEA_READY" />);
    const ideaStep = screen.getByTestId("step-idea");
    expect(ideaStep).toHaveAttribute("data-status", "current");
  });

  it("marks idea as completed and script as current for SCRIPT_GENERATING", () => {
    render(<PipelineStepper currentStage="SCRIPT_GENERATING" />);
    expect(screen.getByTestId("step-idea")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-script")).toHaveAttribute("data-status", "current");
  });

  it("marks idea as completed and script as current for SCRIPT_REVIEW", () => {
    render(<PipelineStepper currentStage="SCRIPT_REVIEW" />);
    expect(screen.getByTestId("step-idea")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-script")).toHaveAttribute("data-status", "current");
  });

  it("marks visual_plan as current for VISUAL_PLAN_GENERATING", () => {
    render(<PipelineStepper currentStage="VISUAL_PLAN_GENERATING" />);
    expect(screen.getByTestId("step-idea")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-script")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-visual_plan")).toHaveAttribute("data-status", "current");
  });

  it("marks assets as current for VISUAL_ASSET_GENERATING", () => {
    render(<PipelineStepper currentStage="VISUAL_ASSET_GENERATING" />);
    expect(screen.getByTestId("step-visual_plan")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-assets")).toHaveAttribute("data-status", "current");
  });

  it("marks audio_subtitles as current for AUDIO_GENERATING", () => {
    render(<PipelineStepper currentStage="AUDIO_GENERATING" />);
    expect(screen.getByTestId("step-assets")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-audio_subtitles")).toHaveAttribute("data-status", "current");
  });

  it("marks audio_subtitles as current for SUBTITLE_GENERATING", () => {
    render(<PipelineStepper currentStage="SUBTITLE_GENERATING" />);
    expect(screen.getByTestId("step-audio_subtitles")).toHaveAttribute("data-status", "current");
  });

  it("marks render as current for RENDER_GENERATING", () => {
    render(<PipelineStepper currentStage="RENDER_GENERATING" />);
    expect(screen.getByTestId("step-audio_subtitles")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-render")).toHaveAttribute("data-status", "current");
  });

  it("marks render as current for FINAL_REVIEW", () => {
    render(<PipelineStepper currentStage="FINAL_REVIEW" />);
    expect(screen.getByTestId("step-render")).toHaveAttribute("data-status", "current");
  });

  it("marks all steps as completed for PUBLISHED", () => {
    render(<PipelineStepper currentStage="PUBLISHED" />);
    for (const step of PIPELINE_STEPS) {
      expect(screen.getByTestId(`step-${step.key}`)).toHaveAttribute("data-status", "completed");
    }
  });

  it("marks current step as failed when failed prop is true", () => {
    render(<PipelineStepper currentStage="SCRIPT_GENERATING" failed={true} />);
    expect(screen.getByTestId("step-idea")).toHaveAttribute("data-status", "completed");
    expect(screen.getByTestId("step-script")).toHaveAttribute("data-status", "failed");
    expect(screen.getByTestId("step-visual_plan")).toHaveAttribute("data-status", "pending");
  });

  it("renders pending steps after current", () => {
    render(<PipelineStepper currentStage="SCRIPT_REVIEW" />);
    expect(screen.getByTestId("step-visual_plan")).toHaveAttribute("data-status", "pending");
    expect(screen.getByTestId("step-assets")).toHaveAttribute("data-status", "pending");
    expect(screen.getByTestId("step-audio_subtitles")).toHaveAttribute("data-status", "pending");
    expect(screen.getByTestId("step-render")).toHaveAttribute("data-status", "pending");
  });

  it("displays step labels", () => {
    render(<PipelineStepper currentStage="IDEA_READY" />);
    expect(screen.getByText("Idea")).toBeInTheDocument();
    expect(screen.getByText("Script")).toBeInTheDocument();
    expect(screen.getByText("Visual Plan")).toBeInTheDocument();
    expect(screen.getByText("Assets")).toBeInTheDocument();
    expect(screen.getByText("Audio / Subs")).toBeInTheDocument();
    expect(screen.getByText("Render")).toBeInTheDocument();
  });

  it("shows checkmark for completed steps", () => {
    render(<PipelineStepper currentStage="VISUAL_PLAN_GENERATING" />);
    // Idea and Script are completed — should show ✓
    const ideaStep = screen.getByTestId("step-idea");
    expect(ideaStep.textContent).toContain("✓");
    const scriptStep = screen.getByTestId("step-script");
    expect(scriptStep.textContent).toContain("✓");
  });

  it("shows ✕ for failed step", () => {
    render(<PipelineStepper currentStage="AUDIO_GENERATING" failed={true} />);
    const audioStep = screen.getByTestId("step-audio_subtitles");
    expect(audioStep.textContent).toContain("✕");
  });

  it("renders as a nav with proper aria-label", () => {
    render(<PipelineStepper currentStage="IDEA_READY" />);
    const nav = screen.getByRole("navigation", { name: "Pipeline progress" });
    expect(nav).toBeInTheDocument();
  });

  it("sets aria-current=step on the current step circle", () => {
    render(<PipelineStepper currentStage="SCRIPT_REVIEW" />);
    const currentCircle = screen.getByTestId("step-script").querySelector("[aria-current='step']");
    expect(currentCircle).toBeInTheDocument();
  });

  it("STAGE_TO_STEP covers all documented stages", () => {
    const expectedStages = [
      "IDEA_READY",
      "SCRIPT_GENERATING",
      "SCRIPT_REVIEW",
      "VISUAL_PLAN_GENERATING",
      "VISUAL_PLAN_REVIEW",
      "VISUAL_ASSET_GENERATING",
      "VISUAL_ASSET_REVIEW",
      "AUDIO_GENERATING",
      "SUBTITLE_GENERATING",
      "RENDER_GENERATING",
      "FINAL_REVIEW",
      "PUBLISHED",
    ];
    for (const stage of expectedStages) {
      expect(STAGE_TO_STEP).toHaveProperty(stage);
    }
  });

  it("PIPELINE_STEPS has exactly 6 entries", () => {
    expect(PIPELINE_STEPS).toHaveLength(6);
  });

  it("handles unknown stage gracefully (all pending)", () => {
    render(<PipelineStepper currentStage="UNKNOWN_STAGE" />);
    // With activeIdx = -1, all steps should be pending (no step matches idx -1)
    for (const step of PIPELINE_STEPS) {
      expect(screen.getByTestId(`step-${step.key}`)).toHaveAttribute("data-status", "pending");
    }
  });
});
