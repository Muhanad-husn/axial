/** Seeding a signed-in session for Playwright (issue #764).
 *
 * No live Supabase project exists for this suite to sign in against (the
 * issue's own hazard), so "signing in" here means driving the real client's
 * own seam directly: `web/src/lib/auth.ts` names `createBrowserClient` at a
 * fixed cookie (`AUTH_COOKIE_NAME`, duplicated here for the same reason
 * `mock-service.mjs` duplicates the wire shapes rather than importing
 * `src/axial` -- this file is plain Node, not the Next bundle, and has no
 * path-aliased access to `@/lib/auth`). Writing a session shaped exactly as
 * `@supabase/ssr`'s browser storage adapter would have written it, before the
 * first navigation, is indistinguishable from a real sign-in to the app: the
 * client reads it from the same place either way.
 *
 * The access token's `sub` claim is the whole of what `mock-service.mjs`
 * trusts (its own module docstring) -- there is no signature to forge
 * because there is no real key to forge against, and there does not need to
 * be one: `src/axial/service/auth.py`'s JWKS verification is proven directly,
 * in Python, against a real key set (issue #763's own suite).
 */

import type { BrowserContext } from "@playwright/test";

const AUTH_COOKIE_NAME = "axial-auth";
const APP_ORIGIN = "http://127.0.0.1:3100";

/** The principal every spec is signed in as unless it asks for a different
 * one -- must match `mock-service.mjs`'s own `DEFAULT_USER_ID`, so the
 * pre-existing specs (`ask.spec.ts`, `history-usage.spec.ts`,
 * `paper.spec.ts`) see exactly the seeded history they did before this issue
 * put every route behind a token. */
export const DEFAULT_USER_ID = "a0000000-0000-4000-8000-000000000001";
export const ANALYST_A_ID = "a0000000-0000-4000-8000-0000000000aa";
export const ANALYST_B_ID = "a0000000-0000-4000-8000-0000000000bb";

function base64url(input: string): string {
  return Buffer.from(input, "utf8").toString("base64url");
}

function fakeAccessToken(userId: string): string {
  const header = base64url(JSON.stringify({ alg: "none", typ: "JWT" }));
  const payload = base64url(
    JSON.stringify({ sub: userId, aud: "authenticated", exp: Math.floor(Date.now() / 1000) + 3600 }),
  );
  return `${header}.${payload}.`;
}

function sessionCookieValue(userId: string): string {
  const session = {
    access_token: fakeAccessToken(userId),
    token_type: "bearer",
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: "e2e-refresh-token",
    user: {
      id: userId,
      aud: "authenticated",
      role: "authenticated",
      email: `${userId}@example.test`,
      app_metadata: {},
      user_metadata: {},
      created_at: new Date().toISOString(),
    },
  };
  // `@supabase/ssr`'s own cookie encoding: a `base64-` prefix over the
  // base64url of the JSON-stringified session (`node_modules/@supabase/ssr/
  // dist/main/cookies.js`, `cookieEncoding: "base64url"`, the library's own
  // default). Small enough to stay one cookie, under the library's own
  // 3180-byte chunking threshold.
  return `base64-${base64url(JSON.stringify(session))}`;
}

/** Seeds `userId` as signed in, before the next navigation. Must run before
 * the first `page.goto` -- `createBrowserClient` reads its cookie once, at
 * construction. */
export async function seedSession(context: BrowserContext, userId: string): Promise<void> {
  await context.addCookies([{ name: AUTH_COOKIE_NAME, value: sessionCookieValue(userId), url: APP_ORIGIN }]);
}

export async function clearSession(context: BrowserContext): Promise<void> {
  await context.clearCookies({ name: AUTH_COOKIE_NAME });
}
