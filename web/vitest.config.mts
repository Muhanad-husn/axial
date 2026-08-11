import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Unit tests sit beside the module they pin. `e2e/` is Playwright's and
    // must not be swept in by vitest's default `*.spec.ts` glob.
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
