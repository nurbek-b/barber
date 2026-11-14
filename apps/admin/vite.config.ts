import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Served by Nginx under /admin/; API and WebSocket on the same origin under /api/.
export default defineConfig({
  base: "/admin/",
  plugins: [react()],
  resolve: { alias: { "@": new URL("./src", import.meta.url).pathname } },
  server: {
    port: 5180,
    proxy: {
      "/api": {
        target: process.env.API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: "es2020",
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query", "@tanstack/react-table"],
          charts: ["recharts"],
          calendar: ["react-big-calendar"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
