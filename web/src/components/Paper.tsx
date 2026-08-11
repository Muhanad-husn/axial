import type { AnalysisRecord, Claim } from "@/lib/api";
import { LEGEND, accentFor, citationSummary, markerLabel, quotesFor } from "@/lib/paper";

const ACCENT_RAIL: Record<string, string> = {
  stated: "bg-stated",
  concluded: "bg-concluded",
  spec: "bg-spec",
};

const ACCENT_MARK: Record<string, string> = {
  stated: "bg-stated/10 text-stated",
  concluded: "bg-concluded/10 text-concluded",
  spec: "bg-spec/12 text-spec",
};

function ClaimRow({ claim }: { claim: Claim }) {
  const accent = accentFor(claim.kind);
  return (
    <div className="flex gap-3.5 pb-4">
      <div className={`w-[3px] flex-none rounded-sm ${ACCENT_RAIL[accent]}`} />
      <div className="min-w-0">
        <p className="m-0 mb-1.5 font-serif text-[15.5px] leading-[1.62] text-ink">{claim.text}</p>
        <div className="flex flex-wrap items-baseline gap-2.5">
          <span
            className={`rounded-[3px] px-1.5 py-[2px] font-mono text-[9px] font-semibold tracking-[0.1em] uppercase ${ACCENT_MARK[accent]}`}
          >
            {markerLabel(claim.kind, claim.grounds)}
          </span>
          <span className="font-mono text-[11px] text-ink2">{citationSummary(claim.grounds)}</span>
        </div>
        {quotesFor(claim.grounds).map((quote) => (
          <blockquote
            key={quote.ref_id}
            className="m-0 mt-2 border-l-2 border-rule pl-2.5 font-serif text-[13px] leading-[1.5] text-ink2 italic"
          >
            &ldquo;{quote.quote}&rdquo;
          </blockquote>
        ))}
      </div>
    </div>
  );
}

/** Screens `2a`/`2b` of the mockup: the paper's claims, each with a
 * coloured rail, its text, and a footer carrying the evidence marker and
 * the citation -- plus the legend that spells the three markers out. This
 * renders exactly `record.claims` in the record's own order; nothing is
 * re-sorted, re-grouped or computed beyond the counts `src/lib/paper.ts`
 * already documents as counts, not decisions. */
export function Paper({ record }: { record: AnalysisRecord }) {
  const disposition = record.interrogation?.disposition;
  const claims = record.claims ?? [];

  if (disposition === "refuse") {
    return (
      <section data-testid="paper" className="pt-1">
        <p className="m-0 text-[12.5px] leading-[1.5] text-ink2">
          The corpus does not support this request
          {record.interrogation?.refusal?.reason ? `: ${record.interrogation.refusal.reason}` : "."}
        </p>
      </section>
    );
  }

  return (
    <>
      <section data-testid="paper" className="pt-1">
        {claims.length === 0 ? (
          <p className="m-0 text-[12.5px] leading-[1.5] text-ink2">(no claims)</p>
        ) : (
          claims.map((claim) => <ClaimRow key={claim.claim_id} claim={claim} />)
        )}
      </section>

      <div
        data-testid="legend"
        className="mt-3 flex flex-col gap-2 rounded-lg bg-sunken px-4 py-3.5"
      >
        {LEGEND.map((row) => (
          <div key={row.accent} className="flex items-baseline gap-2.5 text-[11.5px] leading-[1.45] text-ink2">
            <span
              className={`flex-none rounded-[3px] px-1.5 py-[2px] font-mono text-[9px] font-semibold tracking-[0.1em] uppercase ${ACCENT_MARK[row.accent]}`}
            >
              {row.label}
            </span>
            <span>{row.body}</span>
          </div>
        ))}
      </div>
    </>
  );
}
