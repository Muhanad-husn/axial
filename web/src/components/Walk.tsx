"use client";

import { useEffect, useRef, useState } from "react";

import type { WalkEvent, WalkState } from "@/lib/events";

/** The one phase badge this slice adds (issue #784 slice 03): a `draft`-
 * stage event -- the arc planned, a section as it finishes, the paper
 * written -- gets its own small label, so a reader scanning the walk can
 * tell "drafting the essay" from "reading the corpus" at a glance without
 * parsing the sentence. `null` for every other stage: nothing else on the
 * walk carries a badge today, and adding one for a stage nobody asked to
 * distinguish would be decoration, not information. */
export function stageBadge(detail: WalkEvent["detail"]): string | null {
  return detail.stage === "draft" ? "Drafting" : null;
}

function elapsedLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
}

function useElapsed(startedAt: number | null, running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));
}

/** What Axial is doing, in its own words. This is the screen an analyst
 * stares at for a quarter of an hour, so it is never a bare spinner: every
 * `on_event` the service has sent is on it, in order, with the elapsed
 * clock running. The messages are the service's -- nothing is composed here. */
export function Walk({ walk, startedAt }: { walk: WalkState; startedAt: number | null }) {
  const running = walk.phase === "queued" || walk.phase === "running";
  const elapsed = useElapsed(startedAt, running);

  // A fifteen-minute ask can log dozens of events; the box stays ~6 lines
  // tall and scrolls, so it never pushes the paper below the fold. The whole
  // history is still there on scroll -- this only auto-follows the newest.
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [walk.events.length]);

  return (
    <section className="flex flex-col gap-3 border-l-2 border-rule pl-4">
      <div className="flex items-center gap-2.5 text-[11px] font-semibold text-ink2">
        {running ? (
          <span className="pulse inline-block size-[7px] flex-none rounded-full bg-concluded" />
        ) : (
          <span className="w-[9px] flex-none font-mono text-[10px] text-ink3">
            {walk.phase === "done" ? "✓" : "×"}
          </span>
        )}
        <span>
          {walk.phase === "queued" && walk.events.length === 0
            ? "Queued"
            : walk.phase === "done"
              ? "Read the corpus"
              : walk.phase === "failed"
                ? "Stopped"
                : "Reading"}
        </span>
        <span className="ml-auto font-mono text-[10.5px] text-ink3" aria-label="Elapsed">
          {elapsedLabel(elapsed)}
        </span>
      </div>

      <ol
        ref={listRef}
        className="flex max-h-[10.5em] list-none flex-col gap-2.5 overflow-y-auto p-0"
        data-testid="walk-events"
      >
        {walk.events.map((event, index) => {
          const live = running && index === walk.events.length - 1;
          const badge = stageBadge(event.detail);
          return (
            <li
              key={event.seq ?? `final-${index}`}
              className={`flex items-baseline gap-2.5 text-[12.5px] leading-[1.45] ${
                live ? "text-ink" : "text-ink2"
              }`}
            >
              <span
                className={`w-[9px] flex-none font-mono text-[10px] ${
                  live ? "text-concluded" : "text-ink3"
                }`}
              >
                {live ? "→" : "✓"}
              </span>
              {badge && (
                <span className="flex-none rounded-full border border-rule px-1.5 py-px text-[10px] font-semibold uppercase tracking-wide text-ink3">
                  {badge}
                </span>
              )}
              {/* The running line reads as running: `.shim` (`globals.css`,
                  issue #770) is a left-to-right wash in `--concluded` --
                  the same marker as the arrow and the pulse dot above,
                  never `--stated` (that's "grounded in the source"). It
                  comes off the instant the step completes, and under
                  `prefers-reduced-motion` it never applies at all. */}
              <span className={live ? "shim" : undefined}>{event.message}</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
