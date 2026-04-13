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
    // Dev server binds to localhost by default. Set VITE_DEV_HOST=0.0.0.0
    // to expose on the LAN — be aware this also exposes the API proxy
    // (and VITE_API_KEY if set) to network neighbours.
    server: {
      host: env.VITE_DEV_HOST ?? "127.0.0.1",
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
