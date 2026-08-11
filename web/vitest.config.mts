import path from "node:path";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    // Mirrors tsconfig.json's `@/*` path -- Next's own bundler resolves it,
    // but vitest needs telling. Only `useAsk.ts` (issue #751) imports
    // anything under test through the alias; every prior test file used a
    // relative import instead.
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  test: {
    // Unit tests sit beside the module they pin. `e2e/` is Playwright's and
    // must not be swept in by vitest's default `*.spec.ts` glob.
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
