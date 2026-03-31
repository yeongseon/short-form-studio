import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://api:8000",
      },
      "/artifacts": {
        target: "http://api:8000",
      },
    },
  },
});
