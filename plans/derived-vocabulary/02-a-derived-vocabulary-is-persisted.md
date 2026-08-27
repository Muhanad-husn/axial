# Slice 02: A derived vocabulary is persisted

- **Feature:** derived-vocabulary
- **Issue:** [#806](https://github.com/Muhanad-husn/axial/issues/806)
- **Slice slug:** a-derived-vocabulary-is-persisted
- **Branch:** feat/derived-vocabulary/02-a-derived-vocabulary-is-persisted
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

An operator builds the derived vocabulary once, and it lands on disk: every
answer in every cleared column carries a group id, every group carries a
representative sentence as its label, and a second run over an unchanged
corpus reuses what the first paid for instead of re-clustering.

## Why this slice exists

A grouping that only exists inside a report cannot be joined on. Slice 01
proves the groups are real; this slice turns them into something the retrieval
layer in slice 03 can read, and something the founder can browse without
re-running a clustering pass.

## INVEST check

- **Independent:** depends only on slice 01's module. Nothing downstream exists
  yet, so nothing breaks if the artifact's shape changes later.
- **Valuable:** the vocabulary becomes inspectable and reusable. On its own, an
  operator can open the artifact and read what the corpus's forty recurring
  mechanisms actually are, which is the first time that has been possible.
- **Small:** one writer, one reader, one reuse check. The clustering is slice
  01's, unchanged.
- **Testable:** the artifact is a file; the reuse rule is a pin comparison.
  Both are exercised with an injected encoder.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  an answer store on disk and no vocabulary artifact yet
When   an operator runs `uv run axial vocabulary build`
Then   an artifact is written under `data/vocabulary/` holding, for every
       cleared column, each answer's group id and each group's label and member
       count
And    the artifact records the threshold used per column and the pin of the
       input it was built from
When   the operator runs `uv run axial vocabulary build` a second time with the
       answer store unchanged
Then   the run reuses the persisted fit, re-encodes nothing, and reports that
       it reused rather than rebuilt
```

- **Boundary / endpoint:** CLI — `uv run axial vocabulary build`
- **e2e test type:** CLI integration test against a temporary data directory
  with an injected encoder that counts its own calls
- **e2e test file (planned):** `src/axial/test_cli.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 02-a-derived-vocabulary-is-persisted
edits: src/axial/cli.py
edits: src/axial/test_cli.py
edits: src/axial/vocabulary.py
edits: src/axial/test_vocabulary.py
creates: src/axial/test_vocabulary_build.py
creates: config/vocabulary.yaml
depends-on: 01-the-sentence-columns-are-counted
```

## Inner loop — initial unit test list

- [ ] A built vocabulary maps every population entry to a group id, keyed by
      the note's `chunk_id`, its column, and the element's index within a
      list-valued answer.
- [ ] A group's label is the group's **medoid**, the member with the smallest
      mean cosine distance to the other members, chosen deterministically,
      with ties broken by a stated rule rather than by dict order.
- [ ] A group of one is persisted as a group of one, not dropped. What did not
      group is evidence about the column and must stay visible.
- [ ] The artifact records, per column, the threshold used and the population
      size it was built from.
- [ ] The pin is content-keyed over the rendered input, matching the
      convention merge and Gather already use: a change to the answers
      re-clusters, a change to an unrelated part of the repo does not.
- [ ] An unchanged pin reuses the persisted fit and calls the encoder zero
      times.
- [ ] A changed pin rebuilds and says so, rather than silently serving a stale
      grouping.

## Design notes for the executor

- **Follow the fit-persistence pattern already in the repo.** `axial.names` has
  `_write_fit_artifact` / `_read_fit_artifact` / `_manifest_reusable`, and
  `axial.argmap.build` mirrors it for bag state (issue #677). Mirror it a third
  time rather than inventing a fourth shape.
- **Content-keyed, like the decision logs.** The recorded finding is that merge
  and Gather hash the *rendered* input, so a one-byte render change re-asks the
  corpus and a model change re-asks nothing. Same rule here: the pin is over
  the answer values that went in, nothing else.
- **Which columns are "cleared" is an input, not a guess.** Slice 01's run
  decides which columns have a vocabulary. Carry the cleared set and the
  per-column threshold as configuration written by a human after reading the
  census, not as a rule inferred at runtime.
- **Medoid, not centroid.** The clustering is average-linkage cosine, under
  which the representative member is the one with the smallest mean distance to
  the others, not the one nearest the mean vector. The recorded finding from
  #677B is exactly that a centroid rule over a mean of unit vectors is not the
  linkage criterion it claims. The label is display only, so the harm would be
  cosmetic, but there is no reason to repeat the conflation.
- **The cleared-column configuration needs a home.** The cleared set and the
  per-column threshold come from a human reading slice 01's census. Put them in
  a file this slice declares, not in a constant nobody can find; the Files
  block names it.
- **`data/vocabulary/` is gitignored like the rest of `data/`.** Build it in
  the main checkout.

## Out of scope for this slice (deferred)

- Any retrieval tool reading the artifact. That is slice 03.
- Asking a model to name a group. The label is the medoid member sentence,
  chosen mechanically. A model-written label is a later question and a
  reproducibility risk this slice does not take on.
- Incremental fit: placing a new source's answers into an existing grouping
  without re-clustering. Worth having eventually, the same way `argmap` grew
  it in #677, but not needed to answer this feature's question.
- Merging groups across columns.
- Rendering any of this into the vault.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Built on the real corpus** in `D:/axial`, with the second run observed
      to reuse rather than rebuild. Log to
      `data/logs/<YYYY-MM-DD>-vocabulary-build/` with `run.jsonl`,
      `console.log` and `summary.md`; record the per-column group counts and
      the reuse observation in the summary.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Spec

This slice introduces a new persisted artifact under `data/vocabulary/` with its
own content-keyed pin, so it owes a spec section of its own rather than an
extension of an existing one. Write it in the same branch, beside
`specs/PHASE-B.md` §7.12, which owns the corpus-pin manifest this pin sits
alongside. Slice 01 owes none — it may kill the feature, and writing the
section first is polishing past the bar.

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification: centroid
  corrected to medoid, the cleared-column configuration given a declared home,
  and the owed spec section named.
