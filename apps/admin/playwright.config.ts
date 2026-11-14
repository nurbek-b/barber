import { defineConfig, devices } from "@playwright/test";

const PORT = 5181;

export default defineConfig({
  testDir: "e2e",
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${PORT}/admin/`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    timezoneId: "America/New_York", // the UI must still show salon (Bishkek) time
    locale: "ru-RU",
  },
  webServer: {
    command: `pnpm exec vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/admin/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
