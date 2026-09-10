import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = { target: "http://localhost:8000", changeOrigin: true };

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/ingest": backend,
      "/items": backend,
      "/query": backend,
      "/health": backend,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
