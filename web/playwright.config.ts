import { defineConfig, devices } from "@playwright/test";

const APP_PORT = 3100;
const MOCK_PORT = 8099;

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  // The mock service holds one job list and one kill switch, so the specs
  // share it in order rather than racing each other for it.
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? "list" : "html",
  use: { baseURL: `http://127.0.0.1:${APP_PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `node e2e/mock-service.mjs`,
      env: { MOCK_PORT: String(MOCK_PORT) },
      url: `http://127.0.0.1:${MOCK_PORT}/__health`,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npm run build && npm run start",
      env: {
        PORT: String(APP_PORT),
        AXIAL_API_BASE: `http://127.0.0.1:${MOCK_PORT}`,
      },
      url: `http://127.0.0.1:${APP_PORT}`,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
