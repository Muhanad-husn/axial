# Slice 02: Resolve a validated identifier via Open Library / Crossref, cached, never-halts

- **Feature:** book-metadata-open-library
- **Slice slug:** bibliographic-lookup-cache
- **GitHub issue:** TBD
- **Branch:** feat/book-metadata-open-library/02-bibliographic-lookup-cache
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A new module, `src/axial/bib_lookup.py`, that takes a validated identifier from
slice 01 (`{type: "isbn"|"doi", value: ...}`) and resolves it to canonical
`title`, `author`, `date`, `publisher` fields via **Open Library** (ISBN,
`/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data`) or **Crossref** (DOI,
`/works/{doi}`) — both free, keyless, per the spike's proven client
(`plans/book-metadata-open-library/spike/phase1_lookup.py`, which measured
28/28 = 100% resolution on the real corpus). The raw JSON response is
**cached to disk keyed by the identifier**, so a second call for the same
identifier — a re-run, a retagging pass, anything — never repeats the network
request. A failed, timed-out, or not-found lookup returns an explicit
not-resolved result and **never raises** — this mirrors `holdings.probe`'s own
never-halts contract (`holdings.py:437-442`): intake must be able to proceed
exactly as if no identifier had been found.

## INVEST check

- **Independent:** depends only on slice 01's identifier shape as input; has no
  dependency on `intake.py` or the record shape (that's slice 03).
- **Valuable:** on its own, a reusable, cached, degrade-gracefully bibliographic
  lookup client — the spike proved both APIs return complete records for this
  corpus's shape of source (100% field coverage on title/date/publisher, 96%
  on author).
- **Small:** two HTTP calls, one cache read/write, one response-shape mapper
  per API; no retry/backoff machinery beyond what the stdlib/`requests` already
  gives (a single attempt is enough — see Definition of done on tripwires).
- **Testable:** HTTP is mocked/recorded in tests; no live network in CI, per
  the repo's existing pattern for model/network-touching slices.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a checksum-valid ISBN
When  resolve_isbn is called and Open Library has a matching record
Then  it returns title, author(s), date, and publisher for every field the source provides
And   the raw response is cached to disk keyed by the ISBN
And   a second call for the same ISBN makes no network request

Given a checksum-valid DOI
When  resolve_doi is called and Crossref has a matching work
Then  it returns the same four fields, reading Crossref's `editor` field when `author` is absent (the edited-volume case)

Given an identifier that fails to resolve (not found, network error, timeout, non-JSON response)
When  the corresponding resolve_* function is called
Then  it returns an explicit not-resolved result and does not raise
```

- **Boundary / endpoint:** `axial.bib_lookup.resolve_isbn(isbn)` and
  `axial.bib_lookup.resolve_doi(doi)`; the on-disk cache location (e.g.
  `data/bib_cache/`).
- **Outer test type:** pytest integration test against recorded/stubbed HTTP
  responses (no live network in CI — same posture as the LLM-touching slices'
  recorded-client pattern).
- **Outer test file (planned):**
  `tests/ingestion/test_bibliographic_lookup.py` — test-author, red, locked
  (DEC-1).

## Inner loop — initial unit test list

- [ ] a cached ISBN response short-circuits: the mock HTTP layer asserts zero
      requests on the second call for the same identifier
- [ ] a successful Open Library response maps correctly, joining multiple
      listed authors into one field
- [ ] a successful Crossref response maps correctly; when `author` is empty
      and `editor` is present, `editor` is used (the spike's real gap:
      `decentralization-local-governance-inequality-mena`, an edited volume)
- [ ] an HTTP error, timeout, or non-JSON body returns not-resolved and does
      not raise
- [ ] a genuine "not found" (empty Open Library bibkey result / empty Crossref
      `message`) returns not-resolved, distinguishable from a transport error
      (for future debugging, not necessarily a different caller-visible shape)
- [ ] author-list de-duplication: near-duplicate name-string variants for the
      same edition are not concatenated redundantly (the spike's own bug,
      found on `ayubi-over-stating-the-arab-state`:
      `"Nazih N. M. Ayubi, Nazih N."`) — this slice fixes it, not just avoids
      it
- [ ] the cache file is written under a scratch/data location that is
      gitignored, never committed
- [ ] a request identifies itself with a descriptive `User-Agent` including
      contact info, per both APIs' published etiquette (the spike already does
      this; carry it over)

## Out of scope for this slice (deferred)

- **Deciding whether to trust the fetch over intake's existing read.** Slice
  03's job.
- **The same-work identity guard** (the Mann-volumes cross-check). Slice 03.
- **Skipping the title-page LLM call.** Out of scope for the whole feature —
  see the feature README.
- **Retry/backoff policies, rate-limit pacing.** The corpus is ~30 sources;
  the spike's single-attempt-with-cache approach was sufficient. Add only if
  real-corpus runs show a need (over-engineering tripwire: no speculative
  resilience machinery).

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] No live network call in the test suite; CI has no egress dependency.
- [ ] Cache location is gitignored and documented in the module docstring.
- [ ] Over-engineering tripwires checked: no retry/backoff added beyond a
      single attempt unless justified in the PR body.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-22 planned. Depends on slice 01 (consumes its identifier shape).
