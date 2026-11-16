import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Public booking page (no Telegram), served under /book/ next to /app/ and /admin/.
export default defineConfig({
  base: "/book/",
  plugins: [react()],
  server: {
    port: 5190,
    proxy: {
      "/api": { target: process.env.API_PROXY ?? "http://localhost:8000", changeOrigin: true },
      "/media": { target: process.env.API_PROXY ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { target: "es2020", sourcemap: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
