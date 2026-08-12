"use client";

import { useState } from "react";

import type { Brief } from "@/lib/useAsk";

interface WeightRow {
  source: string;
  weight: string;
}

const EMPTY_ROW: WeightRow = { source: "", weight: "" };

/** The question box: a case, a request, and the source weights behind a
 * disclosure. Weights are the analyst's own instruction (DEC-61) -- Axial
 * never guesses them, and most asks will not use them, so they stay shut. */
export function Composer({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (brief: Brief) => void;
}) {
  const [caseText, setCaseText] = useState("");
  const [request, setRequest] = useState("");
  const [rows, setRows] = useState<WeightRow[]>([EMPTY_ROW]);

  const ready = caseText.trim().length > 0 && request.trim().length > 0 && !busy;

  const updateRow = (index: number, patch: Partial<WeightRow>) =>
    setRows((current) => current.map((row, i) => (i === index ? { ...row, ...patch } : row)));

  const collectWeights = (): Record<string, number> | null => {
    const weights: Record<string, number> = {};
    for (const row of rows) {
      const source = row.source.trim();
      const weight = Number.parseFloat(row.weight);
      if (source.length > 0 && Number.isFinite(weight)) weights[source] = weight;
    }
    return Object.keys(weights).length > 0 ? weights : null;
  };

  // Folded to a compact bar while an ask is running (issue #770): the system
  // doesn't support a follow-up mid-ask, so a live, inviting text box sitting
  // on screen for fifteen minutes invites an interaction that can't work.
  // Purely a function of `busy` -- no state of its own -- so it re-expands
  // the instant `busy` goes false, whether that's the ask finishing or a
  // history row being reopened.
  if (busy) {
    return (
      <div
        data-testid="composer-busy"
        className="mx-4 mb-6 flex items-center gap-2.5 rounded-lg border border-rule bg-panel px-4 py-2.5 text-[11.5px] text-ink2 sm:mx-8"
      >
        <span className="pulse inline-block size-[7px] flex-none rounded-full bg-concluded" aria-hidden="true" />
        Reading the corpus -- the walk above shows every step.
      </div>
    );
  }

  return (
    <form
      className="mx-4 mb-6 rounded-lg border border-rule bg-panel p-4 sm:mx-8"
      onSubmit={(event) => {
        event.preventDefault();
        if (!ready) return;
        onSubmit({ case: caseText.trim(), request: request.trim(), weights: collectWeights() });
      }}
    >
      <label className="mb-1.5 block font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
        Case
      </label>
      <input
        value={caseText}
        onChange={(event) => setCaseText(event.target.value)}
        placeholder="A polity or set of polities, written as the corpus writes them"
        className="mb-3 w-full border-b border-rule bg-transparent pb-1.5 text-[14px] outline-none placeholder:text-ink3 focus:border-ink2"
      />

      <label className="mb-1.5 block font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
        Question
      </label>
      <textarea
        value={request}
        onChange={(event) => setRequest(event.target.value)}
        rows={3}
        placeholder="Ask a question…"
        className="w-full resize-y bg-transparent font-serif text-[17px] leading-[1.5] outline-none placeholder:font-sans placeholder:text-[13px] placeholder:text-ink3"
      />

      <details className="mt-2 border-t border-rule2 pt-3">
        <summary className="cursor-pointer font-mono text-[9.5px] font-semibold tracking-[0.13em] text-ink3 uppercase">
          Weight sources
        </summary>
        <p className="mt-2 text-[11.5px] leading-[1.45] text-ink2">
          Optional. A source id and a multiplier, for instance{" "}
          <span className="font-mono">batatu-1999</span> at{" "}
          <span className="font-mono">2</span>. Axial never infers these.
        </p>
        <div className="mt-2 flex flex-col gap-2">
          {rows.map((row, index) => (
            <div key={index} className="flex gap-2">
              <input
                value={row.source}
                onChange={(event) => updateRow(index, { source: event.target.value })}
                placeholder="source id"
                aria-label={`Source id ${index + 1}`}
                className="min-w-0 flex-1 rounded border border-rule bg-transparent px-2 py-1 font-mono text-[11.5px] outline-none placeholder:text-ink3 focus:border-ink2"
              />
              <input
                value={row.weight}
                onChange={(event) => updateRow(index, { weight: event.target.value })}
                inputMode="decimal"
                placeholder="1.0"
                aria-label={`Weight ${index + 1}`}
                className="w-20 rounded border border-rule bg-transparent px-2 py-1 font-mono text-[11.5px] outline-none placeholder:text-ink3 focus:border-ink2"
              />
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRows((current) => [...current, { ...EMPTY_ROW }])}
            className="cursor-pointer self-start rounded-md border border-rule px-2.5 py-1 text-[11px] font-semibold text-ink2"
          >
            Add a source
          </button>
        </div>
      </details>

      <div className="mt-3 flex justify-end border-t border-rule2 pt-3">
        <button
          type="submit"
          disabled={!ready}
          className="cursor-pointer rounded-md bg-ink px-3.5 py-2 text-[11px] font-semibold text-panel disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? "Reading…" : "Ask"}
        </button>
      </div>
    </form>
  );
}
