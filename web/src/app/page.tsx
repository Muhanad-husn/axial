"use client";

import { useState } from "react";

import { Composer } from "@/components/Composer";
import { ExportControl } from "@/components/ExportControl";
import { MetricsPanel } from "@/components/MetricsPanel";
import { Paper } from "@/components/Paper";
import { TopBar } from "@/components/TopBar";
import { Walk } from "@/components/Walk";
import { useAsk, type Brief } from "@/lib/useAsk";
import { usePaper } from "@/lib/usePaper";

export default function AskPage() {
  const ask = useAsk();
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const paperState = usePaper(ask.askId, ask.walk.phase === "done");

  const start = (brief: Brief) => {
    setStartedAt(Date.now());
    ask.submit(brief);
  };

  const running =
    ask.submitting ||
    (ask.askId !== null && (ask.walk.phase === "queued" || ask.walk.phase === "running"));
  const refusal = ask.submitError ?? ask.walk.error;

  return (
    <>
      <TopBar corpusPin={ask.status?.corpus_pin ?? null} />

      <main className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-6 px-4 pt-6 pb-5 sm:px-8">
        {ask.brief && (
          <section>
            <div className="mb-1.5 font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
              {ask.brief.case}
            </div>
            <p className="m-0 font-serif text-[17px] leading-[1.5]">{ask.brief.request}</p>
          </section>
        )}

        {ask.askId && <Walk walk={ask.walk} startedAt={startedAt} />}

        {refusal && (
          <section
            role="alert"
            data-testid="ask-error"
            className="rounded-lg border border-rule bg-sunken px-4 py-3 text-[12.5px] leading-[1.5]"
          >
            {refusal}
          </section>
        )}

        {ask.walk.phase === "done" && ask.askId && (
          <>
            {paperState.paper ? (
              <>
                <Paper record={paperState.paper.record} />
                <MetricsPanel metrics={paperState.paper.metrics} />
                <ExportControl askId={ask.askId} />
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
                {ask.status?.cached ? " (from cache, at no cost)" : ""}…
              </section>
            )}
          </>
        )}

        {!ask.brief && (
          <section className="text-[12.5px] leading-[1.6] text-ink2">
            State a case, ask a question, and watch Axial read the corpus. An ask takes
            fifteen minutes or so, and the walk shows what it is doing the whole way.
          </section>
        )}
      </main>

      <Composer busy={running} onSubmit={start} />
    </>
  );
}
