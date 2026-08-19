# Slice 01: A malformed citation marker resolves, or fails exactly as now

- **Feature:** 797-marker-hyphen
- **Slice slug:** a-malformed-marker-resolves-or-fails-as-now
- **Branch:** feat/797-marker-hyphen/01-a-malformed-marker-resolves-or-fails-as-now
- **Project directory:** .
- **Status:** built, green
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A drafted marker whose id differs from a real `paper_claim_id` only in
punctuation — `[pc010]` for `[pc-010]` — resolves to that claim, in the
citation index and in the prose itself. A marker that does not correct to
exactly one known claim id still raises `UnresolvableMarkerError`, unchanged.

## Why normalise rather than retry

Both directions were named in the issue and both are cheap. Normalising is
preferable because it is deterministic and costs nothing: a re-ask spends a
model call to fix a punctuation slip and may slip again. The rule stays
strictly non-guessing — the corrected form must already be a claim id the
record carries, and must be the only one it matches. Where it is not, the
§7.5 refusal stands, unweakened. That refusal is correct and this slice does
not touch it.

## Why the prose, and not only the index

`src/axial/paper/reader.py`'s `_MARKER_RUN_RE` matches only `[pc-...]`. A
marker normalised inside `build_citation_index` alone would resolve for the
index and still reach the reader-facing paper as a literal `[pc010]` — a
broken reference in released prose, which is the failure the apparatus
exists to prevent, arriving quietly instead of loudly. So the correction is
applied to the drafted prose, and every later stage reads the corrected
prose: the `cited_so_far` carry, the shape check, the abstract, the index
and both renders.

## What counts as the same id

Case-folded, with every character that is not a letter or a digit removed.
`pc010`, `PC-010` and `pc_010` all key to `pc010`, which is the key
`pc-010` carries. Two known claim ids that collapse to one key make the
marker ambiguous, and an ambiguous marker fails — the point of the rule is
that a correction is a lookup, never a choice.

## INVEST check

- **Independent:** touches the citation boundary only; nothing depends on it.
- **Valuable:** ~3% of drafts died at the last stage after every call was paid
  for (observed 1 of 36, not an established rate).
- **Small:** one normalisation function, one call site in the draft loop.
- **Testable:** the record's citation index and the reader render both show it.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a drafter that emits a citation marker with the hyphen dropped
When  an operator drafts a paper through the paper pipeline
Then  the run completes rather than failing at citation indexing
And   the persisted record's citation index names the real paper_claim_id
And   the reader-facing markdown carries a parenthetical citation, not a raw marker
And   a marker that corrects to no known claim still fails with UnresolvableMarkerError
```

- **Boundary / endpoint:** the paper pipeline (`build_paper_record`), driven
  with a stub client, as `tests/paper/test_paper_pipeline.py` already does.
- **e2e test type:** API/integration test
- **e2e test file (planned):** `tests/paper/test_marker_normalisation.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-a-malformed-marker-resolves-or-fails-as-now
edits: src/axial/paper/citations.py
edits: src/axial/paper/record.py
edits: src/axial/paper/__init__.py
creates: src/axial/paper/test_citations_normalise.py
creates: tests/paper/test_marker_normalisation.py
```

## Inner loop — initial unit test list

- [x] `normalise_markers` leaves prose whose markers all resolve exactly byte-identical.
- [x] `normalise_markers` rewrites `[pc010]` to `[pc-010]` when `pc-010` is a known claim id.
- [x] It is case- and separator-insensitive: `[PC_010]` also rewrites to `[pc-010]`.
- [x] A marker matching no known id under normalisation is left untouched, for `build_citation_index` to refuse.
- [x] A marker whose key matches two known claim ids is left untouched — ambiguity never corrects.
- [x] A marker run `[pc010][pc-011]` rewrites only the malformed member.
- [x] `build_paper_record` normalises each section's prose against the claims known at that point, so `cited_so_far`, the shape check, the abstract, the index and both renders all read the corrected prose.
- [x] `UnresolvableMarkerError` still raises, with the same message, for a marker that does not correct.

## Out of scope for this slice (deferred)

- Retrying the section. The deterministic correction lands first; if malformed
  markers survive it, that is a new observation and a new issue.
- Any change to §7.5's refusal, its message, or its exception type.
- Counting or reporting how often a correction fired. Nothing asked for it,
  and a counter nobody reads is a tripwire.

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [x] Refactor pass complete with the bar green.
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-19 planned.
- 2026-08-19 acceptance test seen red on the exact recorded failure
  (`UnresolvableMarkerError: citation marker [pc002] in section 's1'`), then
  green. `uv run pytest` 2,532 passed in 40s; `uv run ruff check` clean;
  `tests/paper` 220 passed.
