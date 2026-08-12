"use client";

import { useEffect, useState } from "react";

import {
  getCurrentUser,
  isAuthConfigured,
  onAuthStateChange,
  signOut as authSignOut,
  subscribeUnauthorized,
} from "@/lib/auth";

export type SessionState =
  /** `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` are unset --
   * an honest state, never a crash (issue #764's own hazard). */
  | { status: "unconfigured" }
  /** The client-only check for an existing session hasn't resolved yet. */
  | { status: "loading" }
  | { status: "signedOut" }
  | { status: "signedIn"; userId: string; email: string | null };

/** The one place this app decides who, if anyone, is signed in. Runs
 * entirely inside an effect -- never during Next's server render pass, so
 * there is nothing here for hydration to disagree with (the first client
 * render matches the server's: `unconfigured` or `loading`, from a pure env
 * check both sides can make identically).
 *
 * Subscribes to `onAuthStateChange` (a real sign-in, sign-out, or token
 * refresh) and to `subscribeUnauthorized` (`api.ts`'s own `401` signal) --
 * the latter is what turns an expired token mid-walk into a sign-in prompt
 * rather than a screen stuck on a walk that will never finish loading. */
export function useSession(): SessionState & { signOut: () => void } {
  const [state, setState] = useState<SessionState>(() =>
    isAuthConfigured() ? { status: "loading" } : { status: "unconfigured" },
  );

  useEffect(() => {
    if (!isAuthConfigured()) return;
    let active = true;

    getCurrentUser().then((user) => {
      if (!active) return;
      setState(user ? { status: "signedIn", userId: user.id, email: user.email } : { status: "signedOut" });
    });

    const unsubscribeAuth = onAuthStateChange((user) => {
      if (!active) return;
      setState(user ? { status: "signedIn", userId: user.id, email: user.email } : { status: "signedOut" });
    });

    const unsubscribeUnauthorized = subscribeUnauthorized(() => {
      if (!active) return;
      void authSignOut();
      setState({ status: "signedOut" });
    });

    return () => {
      active = false;
      unsubscribeAuth();
      unsubscribeUnauthorized();
    };
  }, []);

  return { ...state, signOut: () => void authSignOut() };
}
