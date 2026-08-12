/** Sign-in, session, and the identity edge this client drives (issue #764).
 *
 * `@supabase/ssr`'s browser client is the ONE implementation: sign-in
 * (Google, email/password), staying signed in, and the access token every
 * call in `api.ts` carries all go through it -- there is no second, test-only
 * auth path. What Playwright drives is this module's own seam: the named
 * cookie (`AUTH_COOKIE_NAME`) `createBrowserClient` is told to use instead of
 * a project-ref-derived default, so a spec can seed a session before it
 * navigates and the real client picks it up exactly as it would a real
 * sign-in's own cookie. `web/e2e/mock-service.mjs` carries the matching auth
 * surface on the service side: a bearer token, checked for presence (and, for
 * the mock's own per-principal scoping, its unverified `sub`) -- the real
 * signature/JWKS check is `src/axial/service/auth.py`'s job and is already
 * proven there (issue #763).
 *
 * `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` are read once,
 * inlined at build time (Next's own convention for `NEXT_PUBLIC_*`). Neither
 * is required for `npm run build` or `npm run dev` to succeed --
 * `getSupabaseClient` returns `null` when either is missing, and
 * `isAuthConfigured` is what the app reads to show an honest "sign-in is not
 * configured" state instead of crashing or silently locking every route.
 */

import { createBrowserClient } from "@supabase/ssr";
import type { Session, SupabaseClient } from "@supabase/supabase-js";

import { clearLiveAskId } from "@/lib/session";

/** The seam Playwright drives (module docstring). A fixed name, independent
 * of `NEXT_PUBLIC_SUPABASE_URL`, so the e2e suite's own dummy project URL
 * (`playwright.config.ts`) never has to agree with a project-ref-derived
 * default it has no real project behind. */
export const AUTH_COOKIE_NAME = "axial-auth";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export function isAuthConfigured(): boolean {
  return Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);
}

let client: SupabaseClient | null | undefined;

/** The one Supabase client this app ever constructs -- memoized, and only
 * ever built in the browser. Next's server render pass has no cookies of its
 * own worth reading here and no session to hold, so it gets `null` rather
 * than a client that would throw the moment it tried to touch `document`. */
export function getSupabaseClient(): SupabaseClient | null {
  if (client !== undefined) return client;
  if (typeof window === "undefined" || !isAuthConfigured()) return null;
  client = createBrowserClient(SUPABASE_URL!, SUPABASE_ANON_KEY!, {
    cookieOptions: { name: AUTH_COOKIE_NAME },
  });
  return client;
}

/** `api.ts`'s own seam: the bearer token every call attaches, or `null` when
 * there is no client or no session -- never thrown, since a signed-out caller
 * asking for a token is the expected, common case, not a failure. */
export async function getAccessToken(): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

export interface AuthUser {
  id: string;
  email: string | null;
}

function toUser(session: Session | null): AuthUser | null {
  if (!session?.user) return null;
  return { id: session.user.id, email: session.user.email ?? null };
}

export async function getCurrentUser(): Promise<AuthUser | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return toUser(data.session);
}

/** Fires on every sign-in, sign-out, and token refresh (the library's own
 * event set) -- `useSession` is the one subscriber, and this is what lets a
 * completed Google redirect or an expired-token forced sign-out (below) show
 * up without a reload. */
export function onAuthStateChange(callback: (user: AuthUser | null) => void): () => void {
  const supabase = getSupabaseClient();
  if (!supabase) return () => {};
  const { data } = supabase.auth.onAuthStateChange((_event, session) => callback(toUser(session)));
  return () => data.subscription.unsubscribe();
}

/** Google sign-in (issue #688) -- the whole client-side mechanism is one
 * redirect out and one redirect back to this origin; Supabase exchanges the
 * code for a session on return (`detectSessionInUrl`, the library's own
 * default), which is what fires `onAuthStateChange` above. */
export async function signInWithGoogle(): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return "Sign-in is not configured for this deployment.";
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.origin },
  });
  return error?.message ?? null;
}

/** Email/password sign-in. No sign-up path anywhere in this client (#688's
 * own line) -- an uninvited email gets Supabase's own refusal, worded by the
 * library, never a form this app built for making an account. */
export async function signInWithPassword(email: string, password: string): Promise<string | null> {
  const supabase = getSupabaseClient();
  if (!supabase) return "Sign-in is not configured for this deployment.";
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  return error?.message ?? null;
}

/** Sign out, and clear this browser's remembered live-ask id (`session.ts`)
 * so the next analyst on the same machine cannot reattach to someone else's
 * running ask -- #688's own line. `scope: "local"` clears this browser only;
 * there is nothing to revoke server-side beyond the JWT itself, which simply
 * expires on its own schedule. */
export async function signOut(): Promise<void> {
  clearLiveAskId();
  const supabase = getSupabaseClient();
  if (!supabase) return;
  await supabase.auth.signOut({ scope: "local" }).catch(() => {});
}

/** Fired by `api.ts` the instant any call comes back `401`: the token this
 * browser is holding was refused at the service's own edge
 * (`src/axial/service/auth.py`), so it is never going to start working again
 * on a retry. `useSession` is the one subscriber -- it forces a local sign-out
 * and the app shows the sign-in screen, which is what issue #764's fourth
 * "done when" bullet asks for: a token that expires mid-walk produces a
 * sign-in prompt, not a stuck screen. */
const unauthorizedListeners = new Set<() => void>();

export function notifyUnauthorized(): void {
  for (const listener of unauthorizedListeners) listener();
}

export function subscribeUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}
