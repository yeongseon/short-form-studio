import { defineConfig } from "vite";

const apiTarget = process.env.API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: apiTarget,
      },
      "/artifacts": {
        target: apiTarget,
      },
    },
  },
});
