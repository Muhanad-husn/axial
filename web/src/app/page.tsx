"use client";

import { useState } from "react";

import { Composer } from "@/components/Composer";
import { ExportControl } from "@/components/ExportControl";
import { HistoryList } from "@/components/HistoryList";
import { MetricsPanel } from "@/components/MetricsPanel";
import { Paper } from "@/components/Paper";
import { SignIn } from "@/components/SignIn";
import { TopBar } from "@/components/TopBar";
import { Walk } from "@/components/Walk";
import type { AskStatus } from "@/lib/api";
import { useAsk, type Brief } from "@/lib/useAsk";
import { useHistory } from "@/lib/useHistory";
import { usePaper } from "@/lib/usePaper";
import { useSession } from "@/lib/useSession";
import { useTheme } from "@/lib/useTheme";
import { useUsage } from "@/lib/useUsage";

/** The gate every route sits behind (issue #764): signed out or unconfigured
 * shows `SignIn` instead of any part of the app underneath, and a fresh
 * `SignedInApp` mounts on every sign-in -- a full remount, so nothing a
 * previous analyst's history/usage/paper hooks fetched can survive into the
 * next analyst's session on the same browser. `theme.ready` gates the same
 * way for the same reason: the app never paints with one analyst's cached
 * theme and then repaints with another's a moment later. */
export default function RootPage() {
  const session = useSession();

  if (session.status === "unconfigured") return <SignIn unconfigured />;
  if (session.status === "loading") return null;
  if (session.status === "signedOut") return <SignIn />;

  return <SignedInApp key={session.userId} userId={session.userId} onSignOut={session.signOut} />;
}

function SignedInApp({ onSignOut }: { userId: string; onSignOut: () => void }) {
  const theme = useTheme();
  const ask = useAsk();
  // Reopening a past ask (issue #746) shows that ask's paper -- its own
  // `AskStatus` row from `GET /asks`, already scoped to this analyst, is
  // everything needed; no second fetch of the row and no read of a
  // `session_id` off anything served, which on a cached row belongs to
  // whoever asked first (#686's trap, carried into this slice). A row still
  // `queued`/`running` has no paper to reopen into -- it reattaches to the
  // walk instead (issue #760), through `useAsk` itself, so it is never
  // routed through `reopened`/`usePaper` at all.
  const [reopened, setReopened] = useState<AskStatus | null>(null);

  // A finished ask -- live or reopened -- is what makes the history list and
  // the usage meters stale, so both refetch once one settles.
  const settledAskId = ask.walk.phase === "done" || ask.walk.phase === "failed" ? ask.askId : null;
  const history = useHistory(settledAskId);
  const usage = useUsage(settledAskId);

  const viewingHistory = reopened !== null;
  const activeAskId = viewingHistory ? reopened.id : ask.askId;
  const paperReady = viewingHistory || ask.walk.phase === "done";
  const paperState = usePaper(activeAskId, paperReady);

  const start = (brief: Brief) => {
    setReopened(null);
    ask.submit(brief);
  };

  // `done` rows still reopen into a paper fetch; anything else has no paper
  // yet, so it reattaches to the walk instead (issue #760).
  const reopen = (row: AskStatus) => {
    if (row.state === "done") {
      setReopened(row);
    } else {
      setReopened(null);
      ask.reattach(row.id, row);
    }
  };

  const status = viewingHistory ? reopened : ask.status;
  const brief = viewingHistory ? (paperState.paper?.record.brief ?? null) : ask.brief;
  const running =
    !viewingHistory &&
    (ask.submitting ||
      (ask.askId !== null && (ask.walk.phase === "queued" || ask.walk.phase === "running")));
  const refusal = viewingHistory ? null : (ask.submitError ?? ask.walk.error);

  // The signed-in app is held off screen until the analyst's own theme is
  // known (`useTheme`'s own docstring) -- an empty body is the whole
  // mechanism, since `layout.tsx`'s inline boot script has already painted a
  // reasonable guess and there is nothing themed to flash yet.
  if (!theme.ready) return null;

  return (
    <>
      <TopBar
        corpusPin={status?.corpus_pin ?? null}
        usage={usage.usage}
        theme={theme.choice}
        onThemeChange={theme.setChoice}
        onSignOut={onSignOut}
      />

      <main className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-6 px-4 pt-6 pb-5 sm:px-8">
        <details data-testid="history" className="rounded-lg border border-rule bg-panel">
          <summary className="cursor-pointer px-4 py-2.5 font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
            History
          </summary>
          <div className="border-t border-rule2 px-4 py-3.5">
            <HistoryList asks={history.asks} onReopen={reopen} />
          </div>
        </details>

        {brief && (
          <section className="hero rounded-lg p-4">
            <div className="mb-1.5 font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
              {brief.case}
            </div>
            <p className="m-0 font-serif text-[17px] leading-[1.5]">{brief.request}</p>
          </section>
        )}

        {!viewingHistory && ask.askId && <Walk walk={ask.walk} startedAt={ask.startedAt} />}

        {refusal && (
          <section
            role="alert"
            data-testid="ask-error"
            className="rounded-lg border border-rule bg-sunken px-4 py-3 text-[12.5px] leading-[1.5]"
          >
            {refusal}
          </section>
        )}

        {(viewingHistory || ask.walk.phase === "done") && activeAskId && (
          <>
            {paperState.paper ? (
              <>
                <Paper record={paperState.paper.record} essay={paperState.paper.essay} />
                <MetricsPanel metrics={paperState.paper.metrics} />
                <ExportControl askId={activeAskId} />
              </>
            ) : paperState.error ? (
              <section
                role="alert"
                data-testid="paper-error"
                className="rounded-lg border border-rule bg-sunken px-4 py-3 text-[12.5px] leading-[1.5]"
              >
                {paperState.error}
              </section>
            ) : (
              <section
                data-testid="paper-loading"
                className="rounded-lg border border-rule bg-panel px-4 py-3.5 text-[12.5px] leading-[1.5] text-ink2"
              >
                Loading the paper
                {status?.cached ? " (from cache, at no cost)" : ""}…
              </section>
            )}
          </>
        )}

        {!brief && (
          <section className="hero rounded-lg p-4 text-[12.5px] leading-[1.6] text-ink2">
            State a case, ask a question, and watch Axial read the corpus. An ask takes
            fifteen minutes or so, and the walk shows what it is doing the whole way.
          </section>
        )}
      </main>

      <Composer busy={running} onSubmit={start} />
    </>
  );
}
