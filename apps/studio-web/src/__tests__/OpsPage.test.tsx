import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import OpsPage from "../pages/OpsPage";

function renderPage() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <OpsPage />
    </MemoryRouter>,
  );
}

describe("OpsPage", () => {
  it("renders operations heading", () => {
    renderPage();
    expect(screen.getByText("Operations")).toBeInTheDocument();
  });

  it("renders ops tools grid", () => {
    renderPage();
    expect(screen.getByTestId("ops-tools-grid")).toBeInTheDocument();
  });

  it("renders all three tool cards", () => {
    renderPage();
    expect(screen.getByTestId("ops-tool-monitoring")).toBeInTheDocument();
    expect(screen.getByTestId("ops-tool-health")).toBeInTheDocument();
    expect(screen.getByTestId("ops-tool-docs")).toBeInTheDocument();
  });

  it("renders tool titles", () => {
    renderPage();
    expect(screen.getByText("Task Monitoring")).toBeInTheDocument();
    expect(screen.getByText("System Health")).toBeInTheDocument();
    expect(screen.getByText("API Documentation")).toBeInTheDocument();
  });

  it("renders system info section", () => {
    renderPage();
    expect(screen.getByTestId("ops-system-info")).toBeInTheDocument();
    expect(screen.getByText("System Information")).toBeInTheDocument();
  });

  it("shows GPU info in system section", () => {
    renderPage();
    expect(screen.getByText(/GTX 1660 SUPER/)).toBeInTheDocument();
  });

  it("renders external links with target=_blank", () => {
    renderPage();
    const monitoringCard = screen.getByTestId("ops-tool-monitoring");
    const link = monitoringCard.querySelector("a");
    expect(link).not.toBeNull();
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.getAttribute("href")).toBe("/flower/");
  });

});
