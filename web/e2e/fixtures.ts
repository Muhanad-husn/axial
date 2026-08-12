import { test as base, expect } from "@playwright/test";

import { DEFAULT_USER_ID, seedSession } from "./auth";

// On this Windows box, the worker-scoped `browser` fixture's own teardown
// (browser.close()) can hang forever: Chromium's temp profile directory gets
// an ACL that makes one subfolder permanently EPERM, and Node's fs.rm()
// retries it without ever giving up (microsoft/playwright#42109 -- closed as
// environment-specific, but reproducible here). Playwright's own runner
// eventually force-kills the stuck worker via an internal watchdog, so the
// run does finish, but only after minutes, and the force-kill itself is
// logged as an error that fails the whole run even though every test passed.
//
// Ask the browser to close ourselves, give it a bounded window, and then exit
// the worker process directly. By this point every test result has already
// been sent to the main process over IPC, so this cannot hide a failure --
// only Playwright's own built-in browser.close() teardown (which we are
// replacing) is skipped.
export const test = base.extend({
  browser: async ({ browser }, use) => {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- Playwright's fixture API, not a React hook.
    await use(browser);
    await Promise.race([
      browser.close(),
      new Promise((resolve) => setTimeout(resolve, 5_000)),
    ]);
    process.exit(0);
  },
  // Every pre-existing spec exercises the signed-in app (issue #764 put every
  // route behind a token), so the default context arrives already signed in
  // as `DEFAULT_USER_ID` -- none of them had to change to keep doing that. A
  // spec that cares about the signed-out or multi-analyst path overrides or
  // clears this itself (`e2e/auth.spec.ts`).
  context: async ({ context }, use) => {
    await seedSession(context, DEFAULT_USER_ID);
    // eslint-disable-next-line react-hooks/rules-of-hooks -- Playwright's fixture API, not a React hook.
    await use(context);
  },
});

export { expect };
