import { defineConfig, devices } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 3100);

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    // Safari's engine: would have caught the removeChild crash.
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    // The API origin is baked in at build time; every request to it is
    // answered by the tests' route mocks, so nothing leaves the machine.
    command: `npm run build && npm run start -- -H 127.0.0.1 -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
    env: { NEXT_PUBLIC_API_BASE_URL: "https://api.e2e.test/v1", NEXT_TELEMETRY_DISABLED: "1" },
  },
});
