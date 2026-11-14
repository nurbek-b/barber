import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Served by Nginx under /app/; the API lives on the same origin under /api/.
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // tunnels for testing inside Telegram (cloudflared / ngrok)
    allowedHosts: [".trycloudflare.com", ".ngrok-free.app", ".ngrok.app", ".ngrok.io"],
    proxy: {
      // one tunnel serves the app, the API and the bot webhook
      "/api/v1/bot": {
        target: process.env.BOT_PROXY ?? "http://localhost:8001",
        changeOrigin: true,
      },
      "/api": { target: process.env.API_PROXY ?? "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    target: "es2020",
    manifest: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom"],
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
