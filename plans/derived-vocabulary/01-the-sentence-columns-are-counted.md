# Slice 01: The sentence columns are counted

- **Feature:** derived-vocabulary
- **Issue:** [#805](https://github.com/Muhanad-husn/axial/issues/805)
- **Slice slug:** the-sentence-columns-are-counted
- **Branch:** feat/derived-vocabulary/01-the-sentence-columns-are-counted
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

An operator runs one command and sees, for each of the twelve sentence-valued
answer columns, how many groups its answers fall into at a sweep of distance
thresholds and how much of the column those groups cover. No model call, no
data written, no corpus pin moved.

## Why this slice exists

This is the go/no-go for the whole feature. The premise is that the sentences
in `mechanism`, `concedes` and the rest repeat *in meaning* even though they
never repeat as strings. That premise has never been tested. This slice tests
it for the price of machine time, and its report is what the founder reads
before anything is built on top.

## INVEST check

- **Independent:** reads `data/answers/` and writes nothing. Depends on no
  other slice and blocks nothing if it is thrown away.
- **Valuable:** it produces the number that decides the feature, and the same
  report is the tightness-setting aid slice 02 needs — the role `names examine`
  plays for the name layer.
- **Small:** one new module, one new CLI subcommand, one report formatter. The
  clustering itself is `_agglomerative_cluster` and `_default_encoder`, which
  already exist in `axial.argmap.build`.
- **Testable:** every unit behaviour is exercised with an injected fake
  encoder and an injected `cluster_fn`, exactly as `argmap.build` and
  `axial.names` already do — no test pays MiniLM's load cost.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  an answer store on disk holding notes whose `mechanism` answers include
       several that say the same thing in different words, and several that
       say unrelated things
When   an operator runs `uv run axial vocabulary examine --columns mechanism`
Then   the report names `mechanism`, its answered-value count, and its distinct
       -string count
And    for each swept distance threshold it gives the number of groups, the
       share of answered values that landed in a group of two or more, and the
       size of the largest group
And    it prints a sample of the largest groups at one threshold, each shown as
       its member sentences, so a reader can judge whether the grouping means
       anything
And    the command makes zero model calls and writes no file
```

- **Boundary / endpoint:** CLI — `uv run axial vocabulary examine`
- **e2e test type:** CLI integration test (`src/axial/test_cli.py`), driving
  `build_parser`/`main` against a temporary answer store with an injected
  encoder, in the style of the existing `names examine` CLI tests
- **e2e test file (planned):** `src/axial/test_cli.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-the-sentence-columns-are-counted
edits: src/axial/cli.py
edits: src/axial/test_cli.py
creates: src/axial/vocabulary.py
creates: src/axial/test_vocabulary.py
```

## Inner loop — initial unit test list

- [ ] Reading a named column from the answer store yields one value per note
      that answered it, with the note's `chunk_id` and `source_id` attached.
- [ ] An abstention is excluded from the population, not clustered — reuse
      `axial.query.reader.is_abstention` rather than re-deciding what an
      abstention is.
- [ ] The literal string `"[]"` and an empty string are excluded on the same
      terms as an abstention, and the count of what was excluded is reported
      rather than silently dropped.
- [ ] A list-valued column (`about`, `arguing_against`) contributes one
      population entry per list element, not one per note.
- [ ] A column whose population is a single value yields one group without
      calling into sklearn at all.
- [ ] The threshold sweep encodes each column exactly once — a second
      threshold must not trigger a second call to the encoder.
- [ ] A column whose population exceeds the declared size ceiling is reported
      as deferred, with its size, and is not clustered and not sampled.
- [ ] The report gives, per threshold, group count, the share of the population
      in a group of size two or more, and the largest group's size.

## Design notes for the executor

- **Reuse, do not rebuild.** `axial.argmap.build` already has
  `_default_encoder` (MiniLM, `normalize_embeddings=True`, batch 256, CPU) and
  `_agglomerative_cluster` (cosine, average linkage, `distance_threshold`).
  Import or lift them; do not write a second encoder.
- **The sweep must not re-encode.** Encoding is the expensive step. Compute the
  linkage once per column and cut it at each threshold rather than refitting
  `AgglomerativeClustering` per threshold — `scipy.cluster.hierarchy.linkage`
  plus `fcluster` gives exactly that, and scipy already arrives with sklearn in
  the `distill` group. If the executor finds a simpler shape that still encodes
  once, take it; the constraint is one encode per column, not the library.
- **The size ceiling is a real constraint, not caution.** Pairwise distances
  are O(n²). `bag_passages` is proven at 6,860 passages. `about` has 20,335
  values. Pick a ceiling, state it in `--help`, and report an over-ceiling
  column as deferred with its size. Never sample a column down to fit — a
  truncated measurement is the failure mode this repo has paid for twice.
- **Thresholds to sweep.** The claim path runs at 0.55. Sweep around it — a
  spread from tight to loose, defaulted in the parser and overridable — so the
  report shows how sensitive each column is rather than asserting one number.
- **`--columns` defaults to all twelve.** Named explicitly in the module, not
  inferred by "everything that isn't a list", because `about` and
  `arguing_against` are list-valued and belong in the twelve.

## Out of scope for this slice (deferred)

- Persisting anything. No artifact, no group ids on disk, no reuse across runs.
  That is slice 02.
- Labelling a group. The report shows member sentences; naming a group is
  slice 02.
- `names`, `uses`, `defines`, `citations`, `position_of`.
- Changing `BAG_DISTANCE_THRESHOLD` or anything else in the live claim path.
- Any model call, for labelling, judging or otherwise.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean — no gate runs it.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Run it on the real corpus.** All twelve columns, full answer store, in
      the main checkout `D:/axial` — never a worktree, where `data/` does not
      exist. Write `data/logs/<YYYY-MM-DD>-vocabulary-census/` with `run.jsonl`,
      `console.log` and `summary.md`, and put the per-column table in the
      summary. A green suite is not the evidence here; the corpus reading is.
- [ ] Report to the founder and **stop**. Slice 02 does not start until the
      number is read.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## What the number has to say for slice 02 to proceed

Stated in advance so the reading is not argued backwards from the result. For
at least one of the twelve columns, at some swept threshold, the grouping must
put a **majority of the column's population into groups of two or more**, and
the largest groups must be legible as one recurring thing when their member
sentences are read side by side. A column that shatters into near-singletons at
every threshold has no vocabulary in it. Slice 02 builds on whichever columns
clear that bar and quietly drops the ones that do not.

## Status / progress log

- 2026-08-27 planned.
