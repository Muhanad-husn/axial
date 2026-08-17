/** Formatting for one claim's evidence marker and citation footer
 * (`web/design/mockup.html` screens 2a/2b). Everything here is a lookup or a
 * count over what `GET /asks/{id}/paper` already sent -- kind-to-marker is a
 * table, not a decision, and no field is re-derived from a chunk id the way
 * `axial.query.reader.source_id_from_chunk_id` does server-side. */

import type { Citation, Ground } from "@/lib/api";

export type Accent = "stated" | "concluded" | "spec";

/** `_claim_to_dict`'s `kind` (`src/axial/answer/record.py`), mapped to this
 * screen's accent colour. An unrecognised kind falls back to `spec`'s
 * accent rather than crashing -- the server names the vocabulary, this is
 * just where to paint it. */
export function accentFor(kind: string): Accent {
  if (kind === "a") return "stated";
  if (kind === "b") return "concluded";
  return "spec";
}

/** How many distinct sources back a claim, read off each ground's own
 * resolved `citation.source_id` (never parsed from `ref_id`). `0` when the
 * server resolved no citation at all -- which is a real case, not a
 * defensive one: `axial.service.citation._resolve_chunk_citation` returns
 * `None` with no vault, no store or an unknown ref, and an `artifact`
 * ground never carries a citation. Counting grounds instead would report
 * chunks as sources and call two passages from one book "2 sources". */
export function sourceCount(grounds: Ground[]): number {
  const resolved = grounds
    .map((ground) => ground.citation?.source_id)
    .filter((id): id is string => Boolean(id));
  return new Set(resolved).size;
}

/** The marker text for one claim (issue #745's own table):
 * `a` -> "stated", `b` -> "concluded across N sources", `c` -> "runs past
 * the books". `N` is the only variable part, and it is a count, not a
 * judgment. A (b) claim whose grounds resolved no citation carries the
 * bare "concluded": the server named no source there, and inventing a
 * number from the ground count would overstate the evidence. */
export function markerLabel(kind: string, grounds: Ground[]): string {
  if (kind === "a") return "stated";
  if (kind === "b") {
    const count = sourceCount(grounds);
    if (count === 0) return "concluded";
    return `concluded across ${count} source${count === 1 ? "" : "s"}`;
  }
  if (kind === "c") return "runs past the books";
  return kind;
}

/** One ground's citation as the mockup's `.cite` text -- the string the
 * server already formatted (`citation.display`, `axial.cite.format_citation`,
 * issue #783). This client composes nothing: a citation that reads one way
 * in a downloaded document and another way on screen is the defect #786 was
 * filed on, and the only way that cannot happen is one formatter.
 *
 * The field-by-field fallback below covers a server that predates #783;
 * it never invents a page number, which does not exist anywhere in this
 * system. `null` when the server resolved nothing at all, so the caller can
 * fall back to the raw `ref_type:ref_id` pointer. */
export function citationLine(citation: Citation | undefined): string | null {
  if (!citation) return null;
  if (citation.display) return citation.display;
  const parts: string[] = [];
  const who = citation.author ?? citation.source_id;
  parts.push(citation.date ? `${who} (${citation.date})` : who);
  if (citation.chapter) parts.push(`ch. ${citation.chapter}`);
  if (citation.section) parts.push(citation.section);
  return parts.join(", ");
}

/** The footer's citation column for one claim: every resolvable ground's
 * `citationLine`, joined; the raw pointer for a ground that resolved
 * nothing; and the honest "no supporting passage" the issue calls out by
 * name for a (c) claim with empty grounds -- a correct thing to render,
 * not a missing value. */
export function citationSummary(grounds: Ground[]): string {
  if (grounds.length === 0) return "no supporting passage";
  return grounds
    .map((ground) => citationLine(ground.citation) ?? `${ground.ref_type}:${ground.ref_id}`)
    .join("; ");
}

/** Every quoted passage a claim's grounds carry (`passage` citation mode
 * only -- `locator` mode never sends `citation.quote`, so this is empty
 * there by construction, not by a branch on the mode). */
export function quotesFor(grounds: Ground[]): { ref_id: string; quote: string }[] {
  return grounds
    .filter((ground): ground is Ground & { citation: Citation & { quote: string } } =>
      Boolean(ground.citation?.quote),
    )
    .map((ground) => ({ ref_id: ground.ref_id, quote: ground.citation.quote }));
}

/** The legend under the paper, in the mockup's own words (issue #745). */
export const LEGEND: { accent: Accent; label: string; body: string }[] = [
  { accent: "stated", label: "stated", body: "A source says this directly." },
  {
    accent: "concluded",
    label: "concluded",
    body: "Axial put sources together. Most likely to be wrong.",
  },
  {
    accent: "spec",
    label: "runs past",
    body: "Beyond what the books support. Labelled, not removed.",
  },
];
