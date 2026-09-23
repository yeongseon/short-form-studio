import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "../pages/SettingsPage";
import type { ProviderConfigState } from "../api/demo";

const remote: ProviderConfigState = {
  provider: "openai", label: "OpenAI", env_var: "OPENAI_API_KEY",
  configured: true, is_local: false, requires_gpu: false,
  status: "configured_unverified", categories: ["llm", "image"],
  unavailable_categories: [], hint: "OpenAI is configured but not yet verified",
};

function response(providers: readonly ProviderConfigState[]) {
  return new Response(JSON.stringify({ providers }));
}

afterEach(() => { vi.restoreAllMocks(); });

describe("SettingsPage read-only contract", () => {
  it("has no credential inputs or browser storage writes when loaded", async () => {
    // Given server-side credentials and a read-only browser surface
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(response([remote]));
    const storage = vi.spyOn(Storage.prototype, "setItem");
    // When settings loads
    const { container } = render(<SettingsPage />);
    await screen.findByText("OpenAI");
    // Then credentials cannot be entered or saved by the browser
    expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /save|update/i })).not.toBeInTheDocument();
    expect(storage).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenCalledWith("/api/creator/models/provider-config", undefined);
  });

  it("announces an error when loading fails", async () => {
    // Given a failed status request
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));
    // When settings loads
    render(<SettingsPage />);
    // Then failure is exposed as an alert
    expect(await screen.findByRole("alert")).toHaveTextContent(/503/);
  });
});

describe("SettingsPage provider readiness", () => {
  it("keeps remote credentials unverified rather than claiming they are active", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([remote]));
    render(<SettingsPage />);
    expect(await screen.findByText("Configured — unverified")).toBeInTheDocument();
    expect(screen.getByText("OPENAI_API_KEY")).toBeInTheDocument();
    expect(screen.getByText(/not yet verified/)).toBeInTheDocument();
    expect(screen.queryByText(/^(Active|Available)$/)).not.toBeInTheDocument();
  });

  it("shows healthy local capabilities without requesting an API key", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([{
      ...remote, provider: "ollama", label: "Ollama", env_var: null,
      is_local: true, requires_gpu: true, status: "configured_available",
      categories: ["llm"], hint: "Ollama is ready",
    }]));
    render(<SettingsPage />);
    expect(await screen.findByText("Available")).toBeInTheDocument();
    expect(screen.getByText(/Local.*GPU required/)).toBeInTheDocument();
    expect(screen.queryByText("OPENAI_API_KEY")).not.toBeInTheDocument();
  });

  it("keeps keyless remote readiness unknown", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([{
      ...remote, provider: "edge_tts", label: "Edge TTS", env_var: null,
      status: "unknown", categories: ["tts"], hint: "Availability has not been checked",
    }]));
    render(<SettingsPage />);
    expect(await screen.findByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("Remote")).toBeInTheDocument();
    expect(screen.queryByText(/^(Not configured|Available)$/)).not.toBeInTheDocument();
    expect(screen.queryByText("OPENAI_API_KEY")).not.toBeInTheDocument();
  });

  it("shows unavailable categories and actionable provider guidance", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([{
      ...remote, status: "configured_unavailable", unavailable_categories: ["image"],
      hint: "Verify OPENAI_API_KEY on the server and retry the provider check",
    }]));
    render(<SettingsPage />);
    expect(await screen.findByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Unavailable capabilities: image/)).toBeInTheDocument();
    expect(screen.getByText(/retry the provider check/)).toBeInTheDocument();
  });

  it("shows missing server configuration without exposing credential values or endpoints", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ providers: [{
      ...remote, status: "not_configured", configured: false,
      hint: "Set OPENAI_API_KEY on the server", api_key: "secret-fixture-value",
      endpoint: "http://private-host:1234",
    }] })));
    const { container } = render(<SettingsPage />);
    expect(await screen.findByText("Not configured")).toBeInTheDocument();
    expect(screen.getByText("OPENAI_API_KEY")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/secret-fixture-value|private-host/);
    expect(container.querySelectorAll("input, textarea")).toHaveLength(0);
  });

  it("retries an error without displaying raw server details", async () => {
    const request = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "secret-fixture-value http://private-host" }), { status: 503 }))
      .mockResolvedValueOnce(response([remote]));
    render(<SettingsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/503/);
    expect(screen.getByRole("alert")).not.toHaveTextContent(/secret-fixture-value|private-host/);
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Configured — unverified")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("refreshes provider status and disables repeat requests while loading", async () => {
    let finish: (value: Response) => void = () => { throw new Error("Request not started"); };
    const request = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(response([remote]))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
    render(<SettingsPage />);
    await screen.findByText("Configured — unverified");
    fireEvent.click(screen.getByRole("button", { name: /refresh/i }));
    expect(screen.getByRole("button", { name: /refresh/i })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    finish(response([{ ...remote, status: "configured_available", hint: "OpenAI is ready" }]));
    expect(await screen.findByText("Available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /refresh/i })).toBeEnabled();
  });

  it("shows an empty inventory without inventing missing providers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(response([]));
    render(<SettingsPage />);
    expect(await screen.findByText(/No providers/)).toBeInTheDocument();
    expect(screen.queryByText("Not configured")).not.toBeInTheDocument();
  });
});
