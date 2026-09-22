import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import IdeaForm from "../components/creator/IdeaForm";

function completeForm() {
  const onSubmit = vi.fn();
  const view = render(<IdeaForm onSubmit={onSubmit} />);
  fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "  My short  " } });
  fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "  A useful idea  " } });
  return { onSubmit, ...view };
}

describe("IdeaForm duration selection", () => {
  it.each([15, 30, 45, 60, 90])("submits the %s-second preset as a number", (seconds) => {
    const { onSubmit } = completeForm();
    fireEvent.change(screen.getByRole("combobox", { name: /Target Duration/ }), { target: { value: String(seconds) } });
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      title: "My short", ideaBrief: "A useful idea", targetDuration: seconds, contentGoal: "",
    });
  });

  it.each([0.5, 5, 125.5, 180, 240])("submits a positive Custom duration of %s without a 180 ceiling", (seconds) => {
    const { onSubmit } = completeForm();
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    const custom = screen.getByRole("spinbutton", { name: /Custom duration/i });
    fireEvent.change(custom, { target: { value: String(seconds) } });
    expect(custom).not.toHaveAttribute("max");
    expect(custom).toBeValid();
    expect(screen.getByText(/approximately 3 minutes/i)).toBeInTheDocument();
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ targetDuration: seconds }));
  });

  it.each(["", "0", "-1", "Infinity", "NaN", "1e309"])("rejects invalid Custom duration %j even on programmatic submit", (value) => {
    const { onSubmit } = completeForm();
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    const custom = screen.getByRole("spinbutton", { name: /Custom duration/i });
    fireEvent.change(custom, { target: { value } });
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(custom).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(/positive.*finite/i);
  });

  it("uses the preset after leaving invalid Custom input", () => {
    const { onSubmit } = completeForm();
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Custom duration/i }), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "30" } });
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ targetDuration: 30 }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("retains Custom input when switching to a preset and back", () => {
    const { onSubmit } = completeForm();
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: /Custom duration/i }), { target: { value: "240" } });
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "15" } });
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ targetDuration: 240 }));
  });

  it("disables both duration controls and submission while submitting", () => {
    const { onSubmit, rerender } = completeForm();
    fireEvent.change(screen.getByLabelText(/Target Duration/), { target: { value: "custom" } });
    rerender(<IdeaForm onSubmit={onSubmit} submitting />);
    fireEvent.submit(screen.getByTestId("idea-form"));
    expect(screen.getByLabelText(/Target Duration/)).toBeDisabled();
    expect(screen.getByRole("spinbutton", { name: /Custom duration/i })).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
