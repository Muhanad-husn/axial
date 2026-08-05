# Findings — book-metadata-open-library exploration

Running log of the spike. Measured, not speculated.

**Environment note:** the spike moved mid-exploration from a cloud sandbox
(egress-blocked, see superseded Phase 1 note below) to the founder's local
machine via `claude --teleport`, then into an isolated worktree at
`.claude/worktrees/book-metadata-explore`. `data/trees` turned out to be empty
on this machine — likely cleared after being consumed downstream — so Phase 0
was re-run directly against the 30 raw source PDFs in `data/sources` (same
`pypdf` read `intake.py` already uses) instead of the docling tree. This
superseded the original tree-based Phase 0 result below and found one more DOI
the tree scan's truncated head-window missed.

## Phase 0 / 0b — identifier coverage (DONE, gate PASSED)

**Current result (0b, PDF-based, `spike/phase0b_scan_pdfs.py`): 28 of 30 real
sources (93%) carry a checksum-valid identifier.**

| Bucket | Count | Notes |
|---|---|---|
| Valid ISBN | 26 | Open Library path |
| DOI only | 2 | Crossref path — `decentralization-local-governance-inequality-mena`, `do-civil-wars-make-or-break-states` |
| Neither | 2 | `heydemann-war-institutions-social-change`, `state-legitimacy-capacity-syrian-conflict` — keep current LLM read |

The 2 identifier-less sources are verified true-negatives (the only
`isbn`/`doi` substring hits in their text are ordinary words — "doing",
"undoing"). They read as a working paper and a policy article — exactly the
population with no ISBN and often no DOI.

*(Superseded original tree-based result, `spike/phase0_scan.py` over a
32-tree corpus pulled from a scratch branch: 27/30, 90% — missed the
`do-civil-wars` DOI because it sits past the tree-scan's 6000-char head
window. Both scans agree on which sources have an ISBN; the PDF scan is the
more complete and current one and is what the coverage gate decision below
is based on.)*

**Gate decision:** coverage is decisive (93%). Proceed.

## Phase 1 — resolve identifiers (DONE, run locally — `spike/phase1_run_pdfs.py`)

Cloud sandbox egress denied `openlibrary.org` / `api.crossref.org` (403,
policy block — reported, not routed around). Re-ran on the founder's machine,
where both hosts are reachable.

**Result: 28/28 identifier-bearing sources resolved (100% hit rate).**

| Field | Present |
|---|---|
| title | 28/28 |
| author | 27/28 |
| date | 28/28 |
| publisher | 28/28 |

Slug-overlap sanity check (fetched title/author vs. the source's filename
slug) ranged 50–100%, all comfortably above the 34% flag threshold — no
mis-typed-identifier flags raised.

## Phase 2 — head-to-head vs current read (DONE — `spike/phase2_compare.py`)

Compared fetched fields against the persisted `data/source_meta/<id>.json`
title-page LLM read, for the 28 resolved sources.

| Field | Agreement | Notes |
|---|---|---|
| Title | 27/28 | The 1 non-match is `ayubi-over-stating-the-arab-state`, where the **current record's title is `None`** — the LLM read failed outright; the fetch filled the gap with the correct title. Net: 28/28 usable. |
| Author | 23/28 (naive) | Every "mismatch" inspected is the **same person**, written differently — diacritics (`Malesevic, Sinisa` vs `Siniša Malešević`) or name order (`Michael Mann` vs `Mann, Michael`). The comparison script's substring match doesn't normalize for either; a real implementation's compare step would need to (or just trust the fetch, which has the *more correct*, diacritic-preserving form). |
| Date | 22/28 (naive) | Most diffs are 1–3 years — Open Library's `publish_date` is often a specific printing/edition date, not the year on this particular copy's copyright page. Expected noise, not an error in either source. |

**One real risk case found:** `mann-sources-of-social-power-v2` fetched
`1986` against a current `1993` — a 7-year gap, much larger than the
printing-date noise seen elsewhere. Mann's four-volume series shares
near-identical titles across volumes, so the slug-overlap guard (title-token
based) would **not** catch a cross-volume ISBN mix-up — all four volumes
score high overlap on "sources of social power" regardless of which volume's
ISBN was actually matched. This is the one place worth a stronger identity
check before trusting a fetch for multi-volume works — e.g. cross-check the
fetched author against the source's known author, not just title-token
overlap, since a wrong-volume fetch still typically shares the true author.

## Bugs found in the spike scripts themselves (not the underlying approach)

- `phase1_lookup.py`'s author-join can duplicate a name when Open Library
  lists near-duplicate author-name variants for one edition (seen on
  `ayubi-over-stating-the-arab-state`: `"Nazih N. M. Ayubi, Nazih N."`).
  Cosmetic — a real implementation would dedupe.
- Crossref's `author` field is empty for edited volumes, which list
  `editor` instead (seen on `decentralization-local-governance-inequality-mena`,
  whose current record correctly has `"Kristen Kao (Editor)"`). A real
  implementation should also read Crossref's `editor` field.

## Overall read

The hypothesis holds, decisively, on the real corpus:

- 93% of sources carry a resolvable identifier.
- 100% of those resolve to real bibliographic data.
- Title accuracy matches or **beats** the current LLM read (one outright gap
  filled). Author/date "mismatches" are almost entirely normalization noise,
  not factual errors, on inspection.
- The one genuine risk (multi-volume cross-edition mix-up) is narrow, occurs
  on a small, identifiable class of sources (multi-volume series with
  near-identical titles), and is guardable with a slightly better check than
  bare title-token overlap.
- Two bonus fields (`publisher`, and a `date` more authoritative than a PDF's
  embedded CreationDate) come along for free — fields the current record
  doesn't carry at all.

This clears the decision gate in `README.md`. Recommend promoting this from
spike to a real feature plan with slices, scoped to: capture + validate
ISBN/DOI from the source (PDF front matter, since the docling tree isn't
reliably retained on disk downstream), Open Library/Crossref lookup with
caching, a merge step that prefers the fetch for identifier-bearing sources,
and a stronger multi-volume identity guard than title overlap alone.
