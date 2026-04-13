import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ConfirmDialog from "../components/creator/ConfirmDialog";

describe("ConfirmDialog", () => {
  const baseProps = {
    open: true,
    title: "Delete item?",
    message: "This action cannot be undone.",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
  };

  it("renders nothing when open is false", () => {
    render(<ConfirmDialog {...baseProps} open={false} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it('has role="dialog" and aria-modal="true"', () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("has aria-labelledby pointing to the title", () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("dialog");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const titleEl = document.getElementById(labelId!);
    expect(titleEl).toHaveTextContent("Delete item?");
  });

  it("has aria-describedby pointing to the message", () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("dialog");
    const descId = dialog.getAttribute("aria-describedby");
    expect(descId).toBeTruthy();
    const descEl = document.getElementById(descId!);
    expect(descEl).toHaveTextContent("This action cannot be undone.");
  });

  it("closes on Escape key", () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog {...baseProps} onCancel={onCancel} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when backdrop is clicked", () => {
    const onCancel = vi.fn();
    render(<ConfirmDialog {...baseProps} onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId("confirm-dialog-backdrop"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onConfirm when confirm button is clicked", () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog {...baseProps} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByTestId("confirm-dialog-confirm"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables buttons when loading", () => {
    render(<ConfirmDialog {...baseProps} loading />);
    const buttons = screen.getAllByRole("button");
    buttons.forEach((btn) => expect(btn).toBeDisabled());
  });

  it("traps focus within dialog (Tab wraps around)", () => {
    render(<ConfirmDialog {...baseProps} />);
    const dialog = screen.getByRole("dialog");
    const buttons = dialog.querySelectorAll<HTMLElement>("button");
    expect(buttons.length).toBe(2);

    // Focus last button, then Tab → should wrap to first
    buttons[buttons.length - 1].focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(buttons[0]);

    // Focus first button, then Shift+Tab → should wrap to last
    buttons[0].focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(buttons[buttons.length - 1]);
  });
});
