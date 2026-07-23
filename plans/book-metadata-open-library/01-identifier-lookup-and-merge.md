# Slice 01: Identifier-based bibliographic lookup — capture, resolve, merge

- **Feature:** book-metadata-open-library
- **Slice slug:** identifier-lookup-and-merge
- **GitHub issue:** [#326](https://github.com/Muhanad-husn/axial/issues/326)
- **Branch:** feat/book-metadata-open-library/01-identifier-lookup-and-merge
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes — the whole feature in one slice, no dependencies

## Goal — the minimum testable behaviour

Give intake a fast, deterministic path to author/title/date/publisher for any
source that carries an ISBN or DOI, end to end in one slice:

1. **Capture and checksum-validate** an ISBN (10 or 13) or DOI from the head
   of a source's own PDF text (the same `pypdf` read `intake.py` already
   performs for embedded metadata — `_pdf_page_texts`, `intake.py:151`), in a
   new pure module `src/axial/identifiers.py`. A corrupted or mistyped
   identifier on the page is dropped, not returned as if valid. No network.
2. **Resolve** a validated identifier against **Open Library** (ISBN,
   `/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data`) or **Crossref**
   (DOI, `/works/{doi}`) — both free, keyless — in a new module
   `src/axial/bib_lookup.py`. The raw response is **cached to disk keyed by
   the identifier**, so a re-run never repeats the network request for the
   same identifier. A failed, timed-out, or not-found lookup returns an
   explicit not-resolved result and **never raises** — mirrors
   `holdings.probe`'s own never-halts contract (`holdings.py:437-442`).
3. **Merge** the result into `intake.py`'s `build_source_meta`, behind a
   **same-work identity guard**: cross-check the fetched author against
   intake's already-known author (its existing embedded-metadata or
   title-page reading) before trusting the fetch. On a passing guard, the
   record's `title`, `author`, `date`, and a new `publisher` field take the
   fetched values, with provenance `"open_library"` or `"crossref"`. On no
   identifier, an unresolved lookup, or a failing guard, intake's existing
   embedded-metadata/title-page behavior is unchanged.

This ports and wires together the spike's already-proven logic
(`plans/book-metadata-open-library/spike/`, see `FINDINGS.md`): 93% coverage,
100% resolution, and title accuracy that matches or beats the current
title-page LLM read on the real 30-source corpus. The current LLM read
(`holdings.py`) is **kept throughout** — sole path for the ~7% of sources
without an identifier, fallback/cross-check for the rest. This slice does not
remove or weaken it.

The identity guard is not optional polish — the spike found a real case it
exists to catch: `mann-sources-of-social-power-v2` resolved to a different
volume's identifier (fetched date off by 7 years). Because Mann's four
volumes share near-identical titles, a title-overlap check alone would not
have flagged it; the guard checks the fetched **author**, not just title
tokens.

## Boundary rule (§7.12) — unchanged

Consistent with the intake-metadata feature's own boundary rule: the record
holds facts about the file as an artifact. An identifier is printed on the
page, and the fields a bibliographic database returns for it describe the
artifact's own stated identity, not an interpretation of its argument.
Nothing here moves into the envelope.

## Record shape change

`data/source_meta/<source_id>.json` gains:

- `publisher`: same three-state shape as `author`/`title`/`date` — `{value,
  provenance}` | `unavailable` | `not_attempted`.
- `identifier`: `{type: "isbn"|"doi", value: <normalized>}` | `null` — the raw
  validated identifier found, kept for audit even when the guard rejects it.
- `author`/`title`/`date`/`publisher` provenance gains two new values:
  `"open_library"` and `"crossref"`.

No existing field's meaning changes.

## INVEST check

- **Independent:** touches only `intake.py`'s `build_source_meta` call site
  plus the two new modules; no other pipeline stage changes.
- **Valuable:** on its own it changes what ships in the persisted record —
  fixes a real observed gap (`ayubi-over-stating-the-arab-state`'s `None`
  title) and adds a field (`publisher`) never captured before, for 93% of the
  corpus, with a measured 100% resolution rate.
- **Small:** two regex/checksum functions, two HTTP calls with a cache, one
  author-overlap guard, three new/changed record fields. No new dependency,
  no retry/backoff machinery, no change to the title-page LLM call itself.
- **Testable:** each of the three stages (capture, lookup, merge) is
  independently unit-testable with fixtures; the full path is testable
  end-to-end with a recorded/stubbed lookup client (no live network).

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given the text of a source's front matter (title page + copyright/ISBN block)
When  identifier capture runs over that text
Then  it returns every checksum-valid ISBN-10/ISBN-13 and syntactically valid DOI found
And   a corrupted check digit or an all-same-digit placeholder is rejected, not returned
And   a source whose front matter carries neither yields no identifier — not an error

Given a checksum-valid ISBN or DOI
When  the corresponding resolver is called and the API has a matching record
Then  it returns title, author(s), date, and publisher for every field the source provides
And   the raw response is cached to disk keyed by the identifier; a second call makes no network request
And   a not-found, network-error, or timeout result is explicit and never raises

Given intake has already produced its existing embedded-metadata/title-page reading for a source
And   a validated identifier resolves
When  the fetched author plausibly overlaps intake's already-known author (the identity guard passes)
Then  the persisted record's title/author/date/publisher are the fetched values, each with provenance "open_library" or "crossref"
And   the record's `identifier` field carries `{type, value}`

Given the fetched author does not plausibly overlap intake's already-known author (the guard fails)
When  the record is built
Then  intake falls back to its existing embedded-metadata/title-page values unchanged
And   `identifier` still records what was found, for audit, but is not used for the four fields

Given no identifier is found, or it fails to resolve
When  the record is built
Then  the record is produced exactly as intake does today, with `identifier: null`
```

- **Boundary / endpoint:** `axial.identifiers.find_isbns`/`find_dois`;
  `axial.bib_lookup.resolve_isbn`/`resolve_doi`; `axial.intake.build_source_meta`
  and its call site in `intake()`. The artifact is the same
  `data/source_meta/<source_id>.json` intake-metadata slice 02 (#285)
  established.
- **Outer test type:** pytest integration test, recorded/stubbed HTTP for the
  lookup client (no live network in CI); fixture front-matter text and PDF
  extracts for capture; a fixture replaying the Mann-volumes near-miss for the
  guard.
- **Outer test file (planned):**
  `tests/ingestion/test_identifier_metadata.py` — test-author, red, locked
  (DEC-1).

## Inner loop — initial unit test list

**Capture / validate**

- [ ] a real ISBN-13 and ISBN-10 (including one ending in `X`) validate;
      corrupted check digits on either fail
- [ ] a hyphenated, labelled front-matter line is captured and normalized to
      digits-only; a bare 13-digit `978`/`979`-prefixed run is still captured
      with no `"ISBN"` word nearby
- [ ] a mistyped ISBN (fails its own checksum) is dropped, never returned as a
      false win
- [ ] an all-same-digit placeholder (`"0-000-00000-0"`) is rejected even
      though it passes the checksum arithmetic
- [ ] a DOI is captured with trailing sentence punctuation stripped
- [ ] text with no identifier returns empty, not an exception; front matter
      with both an ISBN and a DOI returns both
- [ ] a real extracted-PDF-text fixture (normal extraction noise — spacing,
      mid-identifier line breaks) still captures correctly

**Lookup / cache**

- [ ] a cached response short-circuits — zero network requests on a second
      call for the same identifier
- [ ] a successful Open Library response maps title/author/date/publisher,
      joining multiple listed authors without duplicating near-identical name
      variants (the spike's own bug, found on `ayubi-over-stating-the-arab-state`:
      `"Nazih N. M. Ayubi, Nazih N."`)
- [ ] a successful Crossref response maps the same fields; when `author` is
      empty and `editor` is present, `editor` is used (the edited-volume case,
      `decentralization-local-governance-inequality-mena`)
- [ ] an HTTP error, timeout, or non-JSON body returns not-resolved, does not
      raise; a genuine not-found is distinguishable from a transport error
- [ ] the cache file lives under a gitignored scratch location, never
      committed; requests carry a descriptive `User-Agent` with contact info

**Merge / guard**

- [ ] guard passes → fetched title/author/date/publisher win, correct
      provenance recorded, `identifier` populated
- [ ] guard fails (fixture replaying the Mann-volumes case: fetched author
      doesn't match intake's known author) → today's fields kept unchanged;
      `identifier` still recorded but unused
- [ ] the guard itself treats the same person written differently (diacritics,
      "Last, First" vs "First Last" — the spike's own false-mismatch cases,
      e.g. `Malesevic, Sinisa` vs `Siniša Malešević`) as a match, not a false
      rejection
- [ ] no identifier found → record byte-identical to pre-feature behavior
      except `identifier: null`
- [ ] identifier found but unresolved → record identical to pre-feature
      behavior for the four fields; `identifier` still recorded
- [ ] `publisher`'s three-state shape matches the existing
      author/title/date contract
- [ ] the real gap case: a source whose pre-feature title read is `None`
      (replaying `ayubi-over-stating-the-arab-state`) gets a real title when
      the guard passes
- [ ] the record stays byte-unchanged across an envelope regen — the same
      durability guard intake-metadata slice 02 established, still holds

## Out of scope for this slice (deferred)

- **Skipping the title-page LLM call for identifier-confirmed sources.** A
  cost optimization once this fast path has run against more of the corpus;
  not required for correctness, and conflating it here risks regressing the
  fallback path in one change. Backlog item.
- **A guard stronger than author cross-check** (e.g. validating the ISBN's
  publisher-registrant prefix). The author check is sufficient for the one
  real near-miss found; escalate only if real-corpus validation surfaces more
  misses (measure, don't speculate ahead of evidence).
- **Surfacing `publisher` in the vault note.** `vault.py`'s
  `SOURCE_META_FIELDS`/`build_source_meta_block` composition is unchanged;
  whether `publisher` belongs in the note's frontmatter is a separate,
  small follow-up.
- **Retry/backoff policies, rate-limit pacing.** The corpus is ~30 sources;
  the spike's single-attempt-with-cache approach was sufficient.
- **Reading from `data/trees`.** Deliberately not built — the spike found it
  is not reliably retained on disk once consumed downstream.
- **Re-running intake on the existing 30-source corpus to backfill the new
  fields.** Founder-run ops, not part of the slice itself.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered, including the Mann-volumes guard
      fixture; full suite passes locally; outer test GREEN.
- [ ] No live network call in the test suite; CI has no egress dependency.
- [ ] Byte-unchanged-across-regen guard still passing with the new fields.
- [ ] Over-engineering tripwires checked: no retry/backoff beyond a single
      attempt; the guard is one author-overlap check, not a general
      fuzzy-matching framework; no tunables beyond the identifier
      regexes/checksums the spike already proved against the real corpus.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-22 planned, following the completed exploration spike (gate passed
  93% coverage / 100% resolution — see `FINDINGS.md`). Consolidated from three
  slices into one at the founder's request. No dependencies.
- 2026-07-23 **correction, post-review.** The plan above (and the shipped
  first pass, PR-bound commit `746e01b`) assumed the same-work identity
  guard alone catches the Mann-volumes near-miss (see "The identity guard
  is not optional polish" above). The reviewer measured, via a live Open
  Library call, that it does not: `mann-sources-of-social-power-v1`/`v3`/`v4`
  all carry the identical ISBN `9781107028654`, which resolves to author
  "Mann, Michael" — plausibly overlapping every volume's own known author
  "Michael Mann" — so the guard alone passes a wrong-volume fetch straight
  through. **Founder ruling:** front matter carrying more than one distinct
  checksum-valid identifier is ambiguous and abstains — no lookup is
  attempted at all — which catches this case at the root; the author-overlap
  guard is kept unchanged for the single-identifier case, where it still
  does its job (a fetch naming a genuinely different person). See
  `specs/PRODUCT.md` §7.13's "Two independent safeguards" for the corrected,
  shipped description.
- 2026-07-23 **second correction, post real-corpus measurement of the first
  ruling.** Abstaining on ANY multi-identifier capture measured at 93%->37%
  coverage (only 4 of 17 "ambiguous" sources were a genuine cross-work
  mismatch; the rest were harmless hardcover/paperback/ebook ISBN blocks for
  one book). **Founder ruling:** resolve every candidate and compare the
  resolved records (author overlap **and** title agreement, reusing the
  spike's own `phase2_compare.py` substring-containment test) — agreement
  proceeds, disagreement abstains. Shipped and measured live against real
  Open Library data: 90% (27/30) usable (11 unambiguous-single, 16
  multi-resolved-agree, 1 multi-resolved-disagree, 2 neither) — nearly all
  of the original 93% recovered.
  **Open finding, not yet resolved:** none of the 4 real Mann volumes
  abstain under resolve-all-and-compare. Their front-matter ISBNs turn out
  to be eight registrations of ONE combined Open Library catalog record (a
  4-volume box set whose `title` field is the generic series name, with
  each volume's actual subtitle living only in `table_of_contents`, not
  `title`) — every candidate genuinely agrees with every other, so there is
  no disagreement to abstain on. The single-fetch guard then applies
  (author-only, matches), and: `v1`/`v3` lose their known volume-specific
  title suffix for the generic series title; `v4`'s known 2013 date is
  overwritten with the box set's 2012; `v2` (a separate file, its own 4
  candidate ISBNs, also internally agreeing) has its known **1993 date
  overwritten with 1986** — reproducing the exact seven-year-gap near-miss
  the whole guard exists to prevent, because this is a same-title/same-
  author/different-*printing* mismatch, which no author/title comparison
  can see. Separately, `caspersen-unrecognized-states`'s two ISBNs (US
  "Unrecognized States" vs UK "Unrecognised States") are a real same-book
  spelling variant the title-substring check does not recognize as
  agreeing (a small, measured false-abstention cost). Reported to the
  founder for a decision rather than resolved unilaterally.
- 2026-07-23 **third and final correction: gap-fill, not overwrite.** The
  founder reframed the contract entirely rather than patching the
  overwrite design further: the fetch now fills an EMPTY field only
  (`author`/`title`/`date` == `unavailable`); a field the embedded-
  metadata/title-page read already resolved is kept unchanged, always.
  `publisher` (always empty, never captured before) still fills whenever a
  fetch resolves and the guard passes. Both prior safeguards (resolve-all-
  and-compare's disagreement abstention, the author-overlap guard) are
  kept unchanged, gating whether a fill happens rather than whether an
  overwrite happens. This closes the Mann near-miss structurally: every
  Mann volume already has a correct local author/title/date, so a fill
  never touches any of them, and `caspersen-unrecognized-states`'s title-
  substring miss becomes low-stakes (a missed `publisher`, never a
  corruption) -- explicitly NOT chased with fuzzier title matching
  (over-engineering tripwire: no fuzzy matching for a no-corruption case).
  See `specs/PRODUCT.md` §7.13's "Gap-fill, not overwrite" for the shipped
  description.
