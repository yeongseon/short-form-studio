import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import AppShell from "../components/layout/AppShell";
import ProgressDialog from "../components/creator/ProgressDialog";
import ConfirmDialog from "../components/creator/ConfirmDialog";

afterEach(() => { vi.restoreAllMocks(); });

it("allows navigation rows to wrap without a fixed height or hiding links", () => {
  render(<MemoryRouter><AppShell /></MemoryRouter>);
  expect(screen.getByRole("navigation")).toHaveStyle({ flexWrap: "wrap", minHeight: "48px", boxSizing: "border-box" });
  expect(screen.getByRole("navigation").style.height).toBe("");
  for (const name of ["Create", "Projects", "Ops", "Settings"]) {
    expect(screen.getByRole("link", { name })).toBeVisible();
  }
});

it("includes progress dialog padding within the viewport width budget", () => {
  vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
  render(<ProgressDialog open runId={1} expectedStage="RENDER_GENERATING" />);
  expect(screen.getByRole("dialog")).toHaveStyle({
    boxSizing: "border-box", minWidth: "0", maxWidth: "calc(100vw - 32px)",
  });
});

it("includes confirmation dialog padding within the viewport width budget", () => {
  render(<ConfirmDialog open title="Delete Project?" message="Confirm deletion" onConfirm={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.getByRole("dialog")).toHaveStyle({
    boxSizing: "border-box", maxWidth: "calc(100vw - 32px)",
  });
});
