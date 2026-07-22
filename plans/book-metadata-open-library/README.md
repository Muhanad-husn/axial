# Feature: book metadata via identifier lookup (ISBN → Open Library, DOI → Crossref)

Give intake a fast, deterministic path to author/title/date/publisher for any
source that carries an ISBN or DOI: capture and checksum-validate the
identifier from the source's own front matter, resolve it against a free
bibliographic database, and use the result in place of — or as a cross-check
on — the current title-page LLM read. The current read is a single
reasoning-ON model call over messy front-matter prose, and it is where the
recent metadata pain has concentrated (subtitle loss #316, recycled embedded
metadata #285, the whole model cross-check that exists to catch wrong values).
An identifier is a rigid, checksummable token; a bibliographic database returns
canonical fields. This moves the hard problem — normalizing messy
bibliographic text — off the model and onto a database, and asks the
extraction step only to do the easy, deterministic thing: pull a validated
number.

- **Slug:** book-metadata-open-library
- **Created:** 2026-07-22
- **Promoted to feature plan:** 2026-07-22
- **Status:** planned
- **New system?** no. Adds two small modules (`identifiers.py`,
  `bib_lookup.py`) and extends the existing `data/source_meta/<id>.json`
  record (`intake.py`) with an identifier-sourced fast path; the current
  title-page read (`holdings.py`) stays as the sole path for identifier-less
  sources and as the cross-check input for identifier-bearing ones.
- **Project directory:** `.`

## Where this comes from

`plans/book-metadata-open-library/FINDINGS.md` has the full measurement. Short
version, run against the real 30-source corpus:

- **93% coverage** (28/30) carry a checksum-valid ISBN or DOI in their front
  matter.
- **100% resolution** (28/28) of those resolve via Open Library (ISBN) or
  Crossref (DOI).
- **Title agreement 27/28** against the current LLM read — the one non-match
  is a source where the current record's title is `None` (the LLM read failed
  outright) and the fetch fills it correctly.
- Author/date "mismatches" found in the head-to-head were, on inspection,
  almost entirely formatting noise (diacritics, name order, printing-vs-edition
  date offsets), not factual errors.
- **One genuine risk surfaced and scoped in:** a multi-volume work
  (`mann-sources-of-social-power-v2`) resolved to the wrong volume's identifier
  — near-identical titles across volumes mean a title-overlap sanity check
  alone will not catch this. Slice 03 below builds a stronger guard.
- Two fields — `publisher`, and a `date` more authoritative than a PDF's
  embedded `CreationDate` — come along for free; neither is captured today.

The gate (README's original decision criteria) passed decisively. This
document replaces the spike's exploratory framing with a sliced build plan.

## Scope decisions the spike settled

- **Read the identifier from the source PDF's own text (via `pypdf`), not the
  docling tree.** The spike found `data/trees` is not reliably retained on
  this operator's machine — it is cleared once consumed downstream. `intake.py`
  already reads the PDF text layer for the embedded-metadata step
  (`_pdf_page_texts`, `intake.py:151`), so this reuses an existing read rather
  than depending on an artifact that may not exist.
- **The current LLM read stays.** This feature does not remove
  `holdings.probe`'s title-page call. For identifier-less sources it remains
  the only path. For identifier-bearing sources it remains available as a
  cross-check and as the fallback when a lookup fails or the mismatch guard
  rejects a fetch. Whether to skip the model call outright when an identifier
  resolves confidently is a follow-up cost optimization, not in scope here
  (see slice 03's Out of scope) — correctness first, cost second.
- **A title-overlap guard is not enough.** The Mann-volumes near-miss means
  the mismatch guard needs to also check the fetched author against what
  intake already has (embedded metadata or title-page reading), not just
  title tokens.

## Record shape change (§7.12-compatible)

The persisted record (`data/source_meta/<source_id>.json`,
`intake.py:build_source_meta`) gains three fields, all facts about the file as
an artifact (§7.12 — unchanged on re-run against the same bytes), consistent
with what already lives there:

- `publisher`: same three-state shape as `author`/`title`/`date` — `{value,
  provenance}` | `unavailable` | `not_attempted`.
- `identifier`: `{type: "isbn"|"doi", value: <normalized>}` | `null` — the raw
  validated identifier found, kept for audit/debugging and so a re-run doesn't
  need to re-derive it from source text.
- `author`/`title`/`date`/`publisher` provenance gains two new values:
  `"open_library"` and `"crossref"`, alongside the existing `"embedded
  metadata"` and `"title page"`.

No existing field's meaning changes; `unavailable`/`not_attempted` semantics
are unchanged.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [identifier-capture-validate](01-identifier-capture-validate.md) | TBD | Capture ISBN/DOI from a source's front-matter text and keep only checksum/syntax-valid ones; pure, no network | ☐ todo | TBD |
| 02 | [bibliographic-lookup-cache](02-bibliographic-lookup-cache.md) | TBD | Resolve a validated identifier via Open Library (ISBN) or Crossref (DOI), caching the raw response; never halts intake on failure | ☐ todo | TBD |
| 03 | [source-meta-merge-guard](03-source-meta-merge-guard.md) | TBD | Wire the fetch into `build_source_meta`, preferring it over the title-page read when a same-work identity guard passes; extend the record shape | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

GitHub issues are not yet filed for these slices (per the repo's norm of
drafting issue bodies for founder review before filing — the `sprint-plan`
skill does this). File on request.

## Out of scope

- **Removing or weakening the current title-page LLM read.** It remains the
  sole path for identifier-less sources (~7% of the corpus, e.g. working
  papers and policy articles) and the fallback/cross-check input for the rest.
- **Skipping the LLM call for identifier-confirmed sources.** A real cost
  optimization, but a separate decision from correctness — backlog candidate
  after slice 03 ships and the guard has run against more of the corpus.
- **A general-purpose bibliographic-metadata service.** Scope is bounded to
  what `data/source_meta` already models: author, title, date, and now
  publisher — not abstracts, subjects, or full MARC-style records.
- **Paid catalog fallbacks (ISBNdb, Google Books).** Open Library and Crossref
  are both free and keyless; a paid source is a later question only if free
  coverage proves too thin at full-corpus scale (it did not in the spike).
