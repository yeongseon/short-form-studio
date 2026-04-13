import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.API_TARGET ?? "http://localhost:8000";
  const apiKey = env.VITE_API_KEY ?? "";

  const proxyConfig = {
    target: apiTarget,
    ...(apiKey && {
      headers: { "X-API-Key": apiKey },
    }),
  };

  return {
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/api": proxyConfig,
        "/artifacts": proxyConfig,
        "/health": proxyConfig,
        "/healthz": proxyConfig,
        "/docs": proxyConfig,
        "/openapi.json": proxyConfig,
      },
    },
  };
});
