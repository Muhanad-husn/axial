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
thresholds, how much of the column those groups cover, and how many of them
reach more than one source. No model call, no corpus pin moved.

## Why this slice exists

This is the go/no-go for the whole feature. The premise is that the sentences
in `mechanism`, `concedes` and the rest repeat in meaning even though they
never repeat as strings. That premise has never been tested. This slice tests
it for the price of machine time, and its report is what the founder reads
before anything is built on top.

## INVEST check

- **Independent:** reads `data/answers/` and writes only its own report and run
  log. Depends on no other slice. Slice 02 depends on it, both for the module
  and for the decision, so throwing it away throws away the feature — but
  nothing already in the pipeline changes if it does.
- **Valuable:** it produces the number that decides the feature, and the same
  report is the tightness-setting aid slice 02 needs, the role `names examine`
  plays for the name layer.
- **Small:** one new module, one new CLI subcommand, one report formatter. The
  clustering itself is `_agglomerative_cluster` and `_default_encoder`, which
  already exist in `axial.argmap.build`.
- **Testable:** every unit behaviour is exercised with an injected fake encoder
  and an injected `cluster_fn`, exactly as `argmap.build` and `axial.names`
  already do, so no test pays MiniLM's load cost.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  an answer store on disk holding notes from more than one source, whose
       `mechanism` answers include several that say the same thing in different
       words and several that say unrelated things
When   an operator runs `uv run axial vocabulary examine --columns mechanism`
Then   the report names `mechanism`, its answered-value count, and its distinct
       -string count
And    for each swept distance threshold it gives the number of groups, the
       share of answered values in a group of two or more, the size of the
       largest group, and the number of groups whose members come from more
       than one source
And    it names the threshold whose groups it is about to sample, then prints
       the ten largest groups at that same threshold as their member sentences
And    the command makes zero model calls and writes nothing under
       `data/answers/`, `data/chunks/` or any other pipeline store
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
- [ ] An abstention is excluded from the population, not clustered. Reuse
      `axial.query.reader.is_abstention` rather than re-deciding what an
      abstention is.
- [ ] The literal string `"[]"` and an empty string are excluded on the same
      terms as an abstention, and the count of what was excluded is reported
      rather than silently dropped.
- [ ] A list-valued column (`about`, `arguing_against`) contributes one
      population entry per list element, not one per note.
- [ ] A column whose population is a single value yields one group without
      calling into sklearn at all.
- [ ] The threshold sweep encodes each column exactly once. A second threshold
      must not trigger a second call to the encoder.
- [ ] Per threshold the report gives group count, the share of the population
      in a group of size two or more, the largest group's size, and the count
      of groups spanning two or more sources.
- [ ] A column whose population exceeds the size ceiling is measured on a
      random sample, with the sample size and the fact of sampling printed on
      the same row as its figures.
- [ ] The sampled row is marked as sampled everywhere it appears, so no reader
      can mistake it for a whole-column measurement.

## Design notes for the executor

- **Reuse, do not rebuild.** `axial.argmap.build` already has
  `_default_encoder` (MiniLM, `normalize_embeddings=True`, batch 256, CPU) and
  `_agglomerative_cluster` (cosine, average linkage, `distance_threshold`).
  Import or lift them. Do not write a second encoder.
- **The sweep must not re-encode.** Encoding is the expensive step. Compute the
  linkage once per column and cut it at each threshold rather than refitting
  `AgglomerativeClustering` per threshold. `scipy.cluster.hierarchy.linkage`
  plus `fcluster` gives exactly that, and scipy already arrives with sklearn in
  the `distill` group. Any shape that still encodes once is fine; the
  constraint is one encode per column, not the library.
- **Sampling above the ceiling, never silent truncation.** Pairwise distances
  are O(n²) and `bag_passages` is proven at 6,860 passages, so `about` at
  20,335 values needs a ceiling. Above it, draw a random sample of stated size
  and print that it was sampled. This is not the failure the repo has paid for
  twice: that failure was validating a corpus-facing heuristic on truncated
  *books*, where the cut fell at a fixed point and removed whole late chapters.
  A random sample of a column's values, with its size on the row, estimates
  whether the column groups and says how confidently. Silent truncation stays
  banned. Ten of the twelve columns sit under 6,900 values and are measured
  whole either way, so the go/no-go does not rest on a sampled row.
- **Thresholds to sweep.** The claim path runs at 0.55. Sweep a spread around
  it, defaulted in the parser and overridable, so the report shows how
  sensitive each column is rather than asserting one number. The default
  spread is stated in `--help` because the bar below quantifies over it.
- **`--columns` defaults to all twelve.** Named explicitly in the module, not
  inferred by "everything that isn't a list", because `about` and
  `arguing_against` are list-valued and belong in the twelve.
- **The run log is the operator's, not the command's.** The command prints a
  report and writes no pipeline artifact. The `data/logs/` directory in the
  Definition of Done is written by whoever runs it, from the console output.

## Out of scope for this slice (deferred)

- Persisting a grouping. No artifact, no group ids on disk, no reuse across
  runs. That is slice 02.
- Labelling a group. The report shows member sentences; naming is slice 02.
- `names`, `uses`, `defines`, `citations`, `position_of`.
- Changing `BAG_DISTANCE_THRESHOLD` or anything else in the live claim path.
- Any model call, for labelling, judging or otherwise.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean. No gate runs it.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Run it on the real corpus.** All twelve columns, full answer store, in
      the main checkout `D:/axial`, never a worktree where `data/` does not
      exist. The operator writes
      `data/logs/<YYYY-MM-DD>-vocabulary-census/` with `run.jsonl`,
      `console.log` and `summary.md`, and puts the per-column table in the
      summary. A green suite is not the evidence here; the corpus reading is.
- [ ] Report to the founder and **stop**. Slice 02 does not start until the
      number is read.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## The bar for slice 02 to proceed

Stated in advance so the reading is not argued backwards from the result. All
five conditions hold, **at one and the same threshold**, for at least one of
the twelve columns:

1. **At least 20 groups with 5 or more members.** Sets a floor on how much
   recurring structure was found. The README's own hypothesis is that
   `mechanism` holds something like forty recurring mechanisms, so twenty is
   half of what is hoped for.
2. **The largest group holds under 10% of the column's population.** Rules out
   the blob. Every quantity in condition 1 is monotone in the threshold — cut
   loosely enough and the whole column becomes one group — and this is what
   stops that from reading as success.
3. **At least half of those groups draw members from more than one source.** A
   group that is one book talking to itself joins nothing, and the recorded
   finding that only 40.5% of argument-map edges reach another book makes
   single-source groups the expected case rather than a corner one.
4. **The ten largest groups at that threshold are read by the founder, and at
   least seven are legible as one recurring thing.** The command prints them
   and names the threshold it printed them at, so the human read and the
   numeric conditions are evaluated on the same grouping.
5. **The row is not a sampled row.** A sampled column may support the case but
   cannot carry the decision alone.

Note what this bar deliberately does **not** require: that a majority of the
column's values land in a group. Forty real recurring mechanisms covering
1,800 of 5,905 sentences, with the rest genuinely one-off, is a usable
cross-source join and exactly what slice 03 needs. A majority test would fail
it, and a majority test is also passed by a single blob. Neither direction is
what this feature is asking about.

If no column clears all five, slices 02 and 03 do not happen. Slice 04 is
unaffected: it depends on nothing here and is useful whatever this census says.

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification: the bar was
  replaced (a majority test was passable by a blob and failable by the plan's
  own hypothesis), cross-source span added to the report, sampling permitted
  above the ceiling with the sample size printed, and the "writes no file"
  contradiction against the run-log requirement resolved.
