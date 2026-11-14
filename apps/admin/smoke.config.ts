import { defineConfig, devices } from "@playwright/test";

// Post-deploy smoke tests against a live environment (staging): no mocks, no web server.
const base = process.env.SMOKE_BASE_URL ?? "https://localhost";

export default defineConfig({
  testDir: "smoke",
  retries: 2,
  reporter: [["github"], ["list"]],
  use: {
    baseURL: base,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
    locale: "ru-RU",
    // only for a local stack with a self-signed certificate; never set in CI
    ignoreHTTPSErrors: process.env.SMOKE_INSECURE === "1",
  },
});
