import type { AskStatus } from "@/lib/api";

function formatTimestamp(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

/** This analyst's own past asks (`GET /asks`, issue #746, brief per #759):
 * id, state, the case and question that produced it, whether it cost
 * anything, its own timings and, on a failure, the service's own error --
 * rendered exactly as the server named them, with no duration computed and
 * no count re-derived here. A `cached` row cost nothing to produce and is
 * marked as such rather than looking like any other finished ask
 * (`--color-stated`/`concluded`/`spec` are reserved for the paper's own
 * evidence markers per `globals.css`, so this badge is a plain neutral
 * chip, not evidence colour repurposed).
 *
 * No corpus chip (issue #759): every pin in this deployment starts with
 * the same prefix (`TopBar` already names the current one, once), so an
 * eight-character truncation of it distinguished nothing and a row here
 * has no better use for the space.
 *
 * A `done` row reopens straight into its paper -- `GET /asks/{id}/paper`
 * refuses anything else with a `409`. A `queued`/`running` row instead
 * resumes the walk (issue #760): the service survives an API restart and
 * keeps running the ask on its worker, so a row still in flight is not a
 * dead end, it is one `Resume` away from picking up exactly where the
 * stream left off. Only `failed` gets no button -- its own error is already
 * on the row, and there is nothing left to open. Which button appears is a
 * straight read of `ask.state`, decided here; what either button actually
 * does lives in `onReopen`'s caller. */
export function HistoryList({
  asks,
  onReopen,
}: {
  asks: AskStatus[];
  onReopen: (ask: AskStatus) => void;
}) {
  if (asks.length === 0) {
    return <p className="m-0 text-[11.5px] text-ink2">No past asks yet.</p>;
  }

  return (
    <ol data-testid="history-list" className="m-0 flex list-none flex-col gap-2.5 p-0">
      {asks.map((ask) => (
        <li
          key={ask.id}
          className="flex items-center justify-between gap-3 border-b border-rule2 pb-2.5 text-[11.5px] leading-[1.4] last:border-b-0 last:pb-0"
        >
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-[10px] font-semibold text-ink3 uppercase">
                {ask.state}
              </span>
              {ask.cached && (
                <span
                  data-testid="cached-badge"
                  className="rounded-[3px] bg-sunken px-1.5 py-[1px] font-mono text-[9px] font-semibold text-ink2"
                >
                  cached · no cost
                </span>
              )}
            </div>
            {ask.case && (
              <p data-testid="ask-case" className="m-0 break-words font-semibold text-ink">
                {ask.case}
              </p>
            )}
            {ask.question && (
              <p data-testid="ask-question" className="m-0 break-words text-ink2">
                {ask.question}
              </p>
            )}
            <div className="text-ink3">
              {formatTimestamp(ask.created_at)} &rarr; {formatTimestamp(ask.finished_at)}
            </div>
            {ask.error && <div className="text-ink2">{ask.error}</div>}
          </div>
          {ask.state === "done" && (
            <button
              type="button"
              onClick={() => onReopen(ask)}
              className="cursor-pointer flex-none rounded-md border border-rule px-2.5 py-1 text-[11px] font-semibold text-ink2"
            >
              Reopen
            </button>
          )}
          {(ask.state === "queued" || ask.state === "running") && (
            <button
              type="button"
              onClick={() => onReopen(ask)}
              className="cursor-pointer flex-none rounded-md border border-rule px-2.5 py-1 text-[11px] font-semibold text-ink2"
            >
              Resume
            </button>
          )}
        </li>
      ))}
    </ol>
  );
}
