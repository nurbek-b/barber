import { defineConfig, devices } from "@playwright/test";

const PORT = 5174;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}/app/`,
    trace: "retain-on-failure",
    ...devices["Pixel 7"],
  },
  projects: [{ name: "mobile-chromium" }],
  webServer: {
    command: `pnpm exec vite --mode e2e --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/app/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
