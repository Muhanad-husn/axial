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
    // must not be swept in by vitest's default `*.spec.ts` glob. `.tsx`
    // joined the glob for the component tests issue #784 adds
    // (`Essay.test.tsx`, `Paper.test.tsx`) -- the first in this repo to
    // render a component rather than exercise a plain module. Every prior
    // `.test.ts` file stays on the `node` environment declared here; each
    // new `.test.tsx` opts into `jsdom` itself with a `// @vitest-environment
    // jsdom` docblock, so this default is unchanged for everything else.
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "node",
  },
});
