import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import StageActionBar from "../components/creator/StageActionBar";

describe("StageActionBar", () => {
  it("renders nothing when no actions or status message provided", () => {
    const { container } = render(<StageActionBar />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when all actions are hidden", () => {
    const { container } = render(
      <StageActionBar
        save={{ visible: false }}
        approve={{ visible: false }}
        generate={{ visible: false }}
        restart={{ visible: false }}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders the bar when at least one action is visible", () => {
    render(<StageActionBar save={{}} />);
    expect(screen.getByTestId("stage-action-bar")).toBeInTheDocument();
  });

  it("renders save button with default label", () => {
    render(<StageActionBar save={{}} />);
    const btn = screen.getByTestId("action-save");
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent("Save");
  });

  it("renders approve button with default label", () => {
    render(<StageActionBar approve={{}} />);
    expect(screen.getByTestId("action-approve")).toHaveTextContent("Approve");
  });

  it("renders generate button with default label", () => {
    render(<StageActionBar generate={{}} />);
    expect(screen.getByTestId("action-generate")).toHaveTextContent("Generate");
  });

  it("renders restart button with default label", () => {
    render(<StageActionBar restart={{}} />);
    expect(screen.getByTestId("action-restart")).toHaveTextContent("Restart");
  });

  it("renders custom labels when provided", () => {
    render(
      <StageActionBar
        save={{ label: "Save Draft" }}
        approve={{ label: "Approve & Continue" }}
      />,
    );
    expect(screen.getByTestId("action-save")).toHaveTextContent("Save Draft");
    expect(screen.getByTestId("action-approve")).toHaveTextContent("Approve & Continue");
  });

  it("calls onClick when button is clicked", () => {
    const handleSave = vi.fn();
    const handleApprove = vi.fn();
    render(
      <StageActionBar
        save={{ onClick: handleSave }}
        approve={{ onClick: handleApprove }}
      />,
    );

    fireEvent.click(screen.getByTestId("action-save"));
    expect(handleSave).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("action-approve"));
    expect(handleApprove).toHaveBeenCalledTimes(1);
  });

  it("disables button when disabled=true", () => {
    render(<StageActionBar save={{ disabled: true }} />);
    const btn = screen.getByTestId("action-save");
    expect(btn).toBeDisabled();
  });

  it("does not fire onClick when disabled", () => {
    const handler = vi.fn();
    render(<StageActionBar save={{ disabled: true, onClick: handler }} />);
    fireEvent.click(screen.getByTestId("action-save"));
    expect(handler).not.toHaveBeenCalled();
  });

  it("shows loading state with ellipsis and disables button", () => {
    render(<StageActionBar generate={{ loading: true }} />);
    const btn = screen.getByTestId("action-generate");
    expect(btn).toHaveTextContent("Generate…");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-busy", "true");
  });

  it("shows loading with custom label", () => {
    render(<StageActionBar save={{ loading: true, label: "Saving" }} />);
    expect(screen.getByTestId("action-save")).toHaveTextContent("Saving…");
  });

  it("renders status message", () => {
    render(<StageActionBar statusMessage="Draft saved 2m ago" save={{}} />);
    expect(screen.getByTestId("action-status")).toHaveTextContent("Draft saved 2m ago");
  });

  it("renders bar with only status message and no buttons", () => {
    render(<StageActionBar statusMessage="Processing..." />);
    expect(screen.getByTestId("stage-action-bar")).toBeInTheDocument();
    expect(screen.getByTestId("action-status")).toHaveTextContent("Processing...");
    expect(screen.queryByTestId("action-save")).not.toBeInTheDocument();
  });

  it("renders all four buttons simultaneously", () => {
    render(
      <StageActionBar
        save={{}}
        approve={{}}
        generate={{}}
        restart={{}}
      />,
    );
    expect(screen.getByTestId("action-save")).toBeInTheDocument();
    expect(screen.getByTestId("action-approve")).toBeInTheDocument();
    expect(screen.getByTestId("action-generate")).toBeInTheDocument();
    expect(screen.getByTestId("action-restart")).toBeInTheDocument();
  });

  it("only renders visible buttons", () => {
    render(
      <StageActionBar
        save={{}}
        approve={{ visible: false }}
        generate={{}}
        restart={{ visible: false }}
      />,
    );
    expect(screen.getByTestId("action-save")).toBeInTheDocument();
    expect(screen.queryByTestId("action-approve")).not.toBeInTheDocument();
    expect(screen.getByTestId("action-generate")).toBeInTheDocument();
    expect(screen.queryByTestId("action-restart")).not.toBeInTheDocument();
  });

  it("has proper toolbar role and aria-label", () => {
    render(<StageActionBar save={{}} />);
    const toolbar = screen.getByRole("toolbar", { name: "Stage actions" });
    expect(toolbar).toBeInTheDocument();
  });

  it("supports mixed enabled/disabled/loading states", () => {
    render(
      <StageActionBar
        save={{ disabled: false }}
        approve={{ disabled: true }}
        generate={{ loading: true }}
        restart={{}}
      />,
    );
    expect(screen.getByTestId("action-save")).not.toBeDisabled();
    expect(screen.getByTestId("action-approve")).toBeDisabled();
    expect(screen.getByTestId("action-generate")).toBeDisabled();
    expect(screen.getByTestId("action-restart")).not.toBeDisabled();
  });
});
