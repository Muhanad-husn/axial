# Slice 03: Merge the fetch into the source-meta record behind a same-work identity guard

- **Feature:** book-metadata-open-library
- **Slice slug:** source-meta-merge-guard
- **GitHub issue:** TBD
- **Branch:** feat/book-metadata-open-library/03-source-meta-merge-guard
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Wire slices 01 and 02 into `intake.py`'s `build_source_meta`. When a validated
identifier resolves, **cross-check the fetched author against what intake
already knows** (its existing embedded-metadata or title-page reading) before
trusting the fetch. This guard is not optional polish — the spike found a real
case it exists to catch: `mann-sources-of-social-power-v2` resolved to a
different volume's identifier (fetched date off by 7 years), and because
Mann's four volumes share near-identical titles, a title-overlap check alone
would not have flagged it. On a passing guard, the record's `title`, `author`,
`date`, and the new `publisher` field take the fetched values, with provenance
recorded as `"open_library"` or `"crossref"`. On no identifier, an unresolved
lookup, or a failing guard, intake's existing embedded-metadata/title-page
behavior is unchanged — this slice only adds a fast path, it never removes the
fallback.

## Boundary rule (§7.12) — unchanged

Per the intake-metadata feature's own boundary rule, the record holds facts
about the file as an artifact — this addition is consistent with that: an
identifier is printed on the page, and the fields a bibliographic database
returns for it describe the artifact's own stated identity, not an
interpretation of its argument. Nothing here moves into the envelope.

## INVEST check

- **Independent:** the only integration point is `intake.py`'s existing
  `build_source_meta` / `read_bibliographic_fields` call site; slices 01 and
  02 are complete, tested primitives by this point.
- **Valuable:** this is the slice that actually changes what ships in
  `data/source_meta/<id>.json` — the other two are infrastructure. It fixes a
  real, observed gap (a `None` title, `ayubi-over-stating-the-arab-state`) and
  adds a field (`publisher`) the record has never carried.
- **Small:** one guard function (author overlap), one merge function, three
  new/changed record fields; no change to the title-page LLM call itself.
- **Testable:** the guard's pass/fail behavior is directly assertable against
  fixture data, including a fixture replaying the real Mann-volumes case.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given intake has already produced its existing embedded-metadata/title-page reading for a source
And   a validated identifier from slice 01 resolves via slice 02
When  the fetched author plausibly overlaps intake's already-known author (the identity guard passes)
Then  the persisted record's title/author/date/publisher are the fetched values
And   each carries provenance "open_library" or "crossref"
And   the record's `identifier` field carries `{type, value}` for the identifier used

Given the fetched author does not plausibly overlap intake's already-known author (the guard fails — e.g. a cross-volume/cross-edition mismatch)
When  the record is built
Then  intake falls back to its existing embedded-metadata/title-page values unchanged
And   `identifier` still records what was found, for audit, but is not used for title/author/date/publisher

Given no identifier is found, or the identifier fails to resolve
When  the record is built
Then  the record is produced exactly as intake does today, with `identifier: null`
```

- **Boundary / endpoint:** `axial.intake.build_source_meta` and its call site
  in `intake()`; the artifact is the same
  `data/source_meta/<source_id>.json` slice 02 of intake-metadata (#285)
  already established.
- **Outer test type:** pytest integration test, recorded/stub lookup client
  (no network); reuses slice 02's cached-response fixtures.
- **Outer test file (planned):**
  `tests/ingestion/test_source_meta_identifier_merge.py` — test-author, red,
  locked (DEC-1).

## Inner loop — initial unit test list

- [ ] an identifier resolves and the guard passes → fetched title/author/date/
      publisher win, correct provenance (`"open_library"` or `"crossref"`)
      recorded on each
- [ ] an identifier resolves but the guard fails — a fixture replaying the
      Mann-volumes case (fetched author does not match intake's known author)
      → today's embedded-metadata/title-page fields are kept unchanged;
      `identifier` is still recorded but unused for the four fields
- [ ] no identifier found in the source → record is byte-identical to
      pre-feature behavior except `identifier: null`
- [ ] identifier found but the lookup does not resolve (slice 02's
      not-resolved case) → record identical to pre-feature behavior for
      title/author/date/publisher; `identifier` still recorded
- [ ] `publisher`'s three-state shape (`{value, provenance}` |
      `"unavailable"` | `"not_attempted"`) matches the existing contract
      `author`/`title`/`date` already use
- [ ] the real gap case: a source whose pre-feature title read is `None`
      (replaying `ayubi-over-stating-the-arab-state`) gets a real title when
      the guard passes
- [ ] the record stays byte-unchanged across an envelope regen — the same
      durability guard intake-metadata slice 02 established, still holds with
      the three new fields present
- [ ] the identity guard itself: given two author strings that are the same
      person written differently (diacritics, "Last, First" vs "First Last" —
      the spike's own false-mismatch cases, e.g. `Malesevic, Sinisa` vs
      `Siniša Malešević`), the guard correctly treats them as a match, not a
      false rejection

## Out of scope for this slice (deferred)

- **Skipping the title-page LLM call for identifier-confirmed sources.** A
  cost optimization once this fast path has run against more of the corpus;
  not required for correctness, and conflating it here would risk regressing
  the fallback path in one change. Backlog item — see feature README.
- **A guard stronger than author cross-check** (e.g. validating the ISBN's
  publisher-registrant prefix against the source). The author check is
  sufficient for the one real near-miss found; escalate only if real-corpus
  validation surfaces more misses (`validate-heuristics-on-real-corpus`
  principle — measure, don't speculate ahead of evidence).
- **Surfacing `publisher` in the vault note.** `vault.py`'s
  `SOURCE_META_FIELDS` / `build_source_meta_block` composition is unchanged by
  this slice; whether `publisher` belongs in the note's frontmatter is a
  separate, small follow-up decision.
- **Re-running intake on the existing 30-source corpus to backfill the new
  fields.** Founder-run ops, not part of the slice itself.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered, including the Mann-volumes guard
      fixture; full suite passes locally; outer test GREEN.
- [ ] Byte-unchanged-across-regen guard still passing with the new fields.
- [ ] Over-engineering tripwires checked: the guard is one author-overlap
      check, not a general fuzzy-matching framework.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-22 planned. Depends on slices 01 and 02.
