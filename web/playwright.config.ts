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
        // A syntactically real, never-contacted project (issue #764): no live
        // Supabase project exists for this suite (the issue's own hazard), so
        // this only has to be well-formed enough for `createBrowserClient` to
        // construct -- every spec seeds its own session directly
        // (`e2e/auth.ts`) rather than driving a real sign-in against it. Port
        // 9 (`discard`) refuses fast on this box, so `signOut`'s own best-
        // effort server call (`@supabase/auth-js`) fails quickly rather than
        // waiting out a DNS timeout.
        NEXT_PUBLIC_SUPABASE_URL: "http://127.0.0.1:9",
        NEXT_PUBLIC_SUPABASE_ANON_KEY: "e2e-anon-key",
      },
      url: `http://127.0.0.1:${APP_PORT}`,
      // Covers `next build` plus `next start`, not just the server's own
      // boot. The build's TypeScript pass alone runs 70-80s on a developer
      // box and the whole command lands around 150s, so the old 180s left no
      // margin at all: a cold cache or a loaded machine timed the suite out
      // before a single spec ran.
      timeout: 420_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
