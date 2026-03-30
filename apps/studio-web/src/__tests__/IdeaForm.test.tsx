import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import IdeaForm from "../components/creator/IdeaForm";

function renderIdeaForm(props: Partial<Parameters<typeof IdeaForm>[0]> = {}) {
  const onSubmit = props.onSubmit ?? vi.fn();
  return {
    onSubmit,
    ...render(<IdeaForm onSubmit={onSubmit} submitting={props.submitting} error={props.error} />),
  };
}

describe("IdeaForm", () => {
  it("renders all form fields", () => {
    renderIdeaForm();
    expect(screen.getByLabelText(/Title/)).toBeTruthy();
    expect(screen.getByLabelText(/Idea Brief/)).toBeTruthy();
    expect(screen.getByLabelText(/Target Duration/)).toBeTruthy();
    expect(screen.getByLabelText(/Content Goal/)).toBeTruthy();
  });

  it("has data-testid on form element", () => {
    renderIdeaForm();
    expect(screen.getByTestId("idea-form")).toBeTruthy();
  });

  it("target duration defaults to 60", () => {
    renderIdeaForm();
    const input = screen.getByLabelText(/Target Duration/) as HTMLInputElement;
    expect(input.value).toBe("60");
  });

  it("allows typing in all fields", () => {
    renderIdeaForm();

    const titleInput = screen.getByLabelText(/^Title/) as HTMLInputElement;
    fireEvent.change(titleInput, { target: { value: "My Video" } });
    expect(titleInput.value).toBe("My Video");

    const briefInput = screen.getByLabelText(/Idea Brief/) as HTMLTextAreaElement;
    fireEvent.change(briefInput, { target: { value: "A cooking tutorial" } });
    expect(briefInput.value).toBe("A cooking tutorial");

    const durationInput = screen.getByLabelText(/Target Duration/) as HTMLInputElement;
    fireEvent.change(durationInput, { target: { value: "90" } });
    expect(durationInput.value).toBe("90");

    const goalInput = screen.getByLabelText(/Content Goal/) as HTMLInputElement;
    fireEvent.change(goalInput, { target: { value: "educational" } });
    expect(goalInput.value).toBe("educational");
  });

  it("calls onSubmit with form data when submitted", () => {
    const { onSubmit } = renderIdeaForm();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Test Title" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "Test brief" } });
    fireEvent.change(screen.getByLabelText(/Content Goal/), { target: { value: "entertainment" } });

    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).toHaveBeenCalledWith({
      title: "Test Title",
      ideaBrief: "Test brief",
      targetDuration: 60,
      contentGoal: "entertainment",
    });
  });

  it("trims whitespace from text fields on submit", () => {
    const { onSubmit } = renderIdeaForm();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "  Spaced Title  " } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "  brief  " } });
    fireEvent.change(screen.getByLabelText(/Content Goal/), { target: { value: "  fun  " } });

    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).toHaveBeenCalledWith({
      title: "Spaced Title",
      ideaBrief: "brief",
      targetDuration: 60,
      contentGoal: "fun",
    });
  });

  it("does not submit when title is empty", () => {
    const { onSubmit } = renderIdeaForm();

    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "Has brief" } });
    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not submit when ideaBrief is empty", () => {
    const { onSubmit } = renderIdeaForm();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Has title" } });
    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not submit when title is whitespace-only", () => {
    const { onSubmit } = renderIdeaForm();

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "   " } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "Brief" } });
    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not submit when submitting is true", () => {
    const { onSubmit } = renderIdeaForm({ submitting: true });

    fireEvent.change(screen.getByLabelText(/^Title/), { target: { value: "Title" } });
    fireEvent.change(screen.getByLabelText(/Idea Brief/), { target: { value: "Brief" } });
    fireEvent.submit(screen.getByTestId("idea-form"));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables inputs when submitting", () => {
    renderIdeaForm({ submitting: true });

    expect(screen.getByLabelText(/^Title/)).toBeDisabled();
    expect(screen.getByLabelText(/Idea Brief/)).toBeDisabled();
    expect(screen.getByLabelText(/Target Duration/)).toBeDisabled();
    expect(screen.getByLabelText(/Content Goal/)).toBeDisabled();
  });

  it("does not show error when error is null", () => {
    renderIdeaForm();
    expect(screen.queryByTestId("idea-form-error")).toBeNull();
  });

  it("shows error message when error is provided", () => {
    renderIdeaForm({ error: "Something went wrong" });
    const errorEl = screen.getByTestId("idea-form-error");
    expect(errorEl).toBeTruthy();
    expect(errorEl.textContent).toBe("Something went wrong");
    expect(errorEl).toHaveAttribute("role", "alert");
  });

  it("marks title and idea brief as required", () => {
    renderIdeaForm();
    expect(screen.getByLabelText(/^Title/)).toHaveAttribute("required");
    expect(screen.getByLabelText(/Idea Brief/)).toHaveAttribute("required");
  });

  it("has duration constraints min=10 max=180", () => {
    renderIdeaForm();
    const input = screen.getByLabelText(/Target Duration/) as HTMLInputElement;
    expect(input.min).toBe("10");
    expect(input.max).toBe("180");
  });
});
