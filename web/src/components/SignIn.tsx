"use client";

import { useState } from "react";

import { signInWithGoogle, signInWithPassword } from "@/lib/auth";

/** The gate every route sits behind (issue #688/#764): a signed-out visitor
 * lands here, never on an app that silently `401`s underneath them. No
 * sign-up form anywhere in this component -- an uninvited email gets
 * Supabase's own refusal from `signInWithPassword`, worded by the library. */
export function SignIn({ unconfigured = false }: { unconfigured?: boolean }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (unconfigured) {
    return (
      <main className="mx-auto flex w-full max-w-[420px] flex-1 flex-col items-center justify-center gap-3 px-4 text-center">
        <span className="text-[13px] font-semibold tracking-[0.14em] uppercase">Axial</span>
        <p data-testid="signin-unconfigured" className="m-0 text-[12.5px] leading-[1.6] text-ink2">
          Sign-in is not configured for this deployment. Set
          <code className="mx-1 font-mono text-[11px]">NEXT_PUBLIC_SUPABASE_URL</code>
          and
          <code className="mx-1 font-mono text-[11px]">NEXT_PUBLIC_SUPABASE_ANON_KEY</code>
          to enable it.
        </p>
      </main>
    );
  }

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    const message = await signInWithPassword(email, password);
    setSubmitting(false);
    if (message) setError(message);
  };

  return (
    <main className="mx-auto flex w-full max-w-[360px] flex-1 flex-col justify-center gap-5 px-4">
      <span className="text-center text-[13px] font-semibold tracking-[0.14em] uppercase">Axial</span>

      <button
        type="button"
        onClick={() => void signInWithGoogle().then((message) => message && setError(message))}
        className="cursor-pointer rounded-md border border-rule px-3.5 py-2 text-[12.5px] font-semibold text-ink"
      >
        Sign in with Google
      </button>

      <div className="flex items-center gap-2 text-[10.5px] text-ink3">
        <span className="h-px flex-1 bg-rule2" />
        or
        <span className="h-px flex-1 bg-rule2" />
      </div>

      <form onSubmit={submitPassword} className="flex flex-col gap-3">
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Email"
          autoComplete="email"
          className="w-full border-b border-rule bg-transparent pb-1.5 text-[13px] outline-none placeholder:text-ink3 focus:border-ink2"
        />
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          className="w-full border-b border-rule bg-transparent pb-1.5 text-[13px] outline-none placeholder:text-ink3 focus:border-ink2"
        />
        <button
          type="submit"
          disabled={submitting || !email || !password}
          className="cursor-pointer rounded-md bg-ink px-3.5 py-2 text-[11px] font-semibold text-panel disabled:cursor-not-allowed disabled:opacity-40"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      {error && (
        <section role="alert" data-testid="signin-error" className="text-[11.5px] leading-[1.5] text-ink2">
          {error}
        </section>
      )}
    </main>
  );
}
