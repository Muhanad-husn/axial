# Slice 02: A derived vocabulary is persisted

- **Feature:** derived-vocabulary
- **Issue:** [#806](https://github.com/Muhanad-husn/axial/issues/806)
- **Slice slug:** a-derived-vocabulary-is-persisted
- **Branch:** feat/derived-vocabulary/02-a-derived-vocabulary-is-persisted
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Rewritten 2026-08-27**, after slice 01 shipped and ran on the real corpus.
> The earlier version of this plan persisted an embedding *clustering* fit:
> distance thresholds, medoid labels, an encoder call count. Slice 01 built that
> instrument, ran it, and rejected it. Clustering measures wording, not meaning,
> and gave 772 wording groups on `mechanism` where a model reading a sample
> named 20 categories. What shipped is model categorisation. This plan persists
> that. Nothing below clusters anything.

## The vocabulary is a tree, not a list

**Founder ruling, 2026-08-28, before any of this is built.**

A category holding roughly 295 notes is a browsing unit, not a retrieval unit.
That is not an argument against categories. It is an argument against stopping
at one level. Coarse is the top of a hierarchy, not the whole of it.

The same instrument that named 20 mechanisms from a sample of the column will
name sub-categories from a sample of one category. Twenty categories of about
ten sub-categories each lands at roughly 30 notes per node, which is the band
the name index already works in: 30 to 200 notes across five or more sources.
The repo has made this move before, from a flat table to a relational one, and
it paid.

Three reasons this is the shape and not scope creep:

- **It needs no new machinery.** A second level is slice 01's command pointed at
  a subset. The five-condition bar applies unchanged to a sub-population.
- **It is cheap.** Every value is assigned once at about $0.08 for `mechanism`;
  assigning those same values within their own category costs about the same
  again, plus one propose call per category.
- **It is the direct fix for the only failure slice 01 found.** Five columns
  cleared every condition except the ceiling on the largest category —
  `comparison` at 50.5%, `concedes` 27.0%, `stops_holding` 25.5%, `assumes`
  25.2%. A blob is a category that wants splitting. A second level is what
  splits it, and it may make all twelve columns usable rather than seven.

**What this slice must therefore do.** Ship depth 1, with an artifact and a
scheme file that admit depth 2 without a migration.

- A category carries a parent id. At depth 1 every parent is null, and the field
  exists anyway.
- `config/vocabulary.yaml` nests. A v1 scheme has depth 1; its shape does not
  assume depth 1.
- The scheme version covers the whole tree, so adding a level is a version bump
  rather than a second versioning scheme.
- Assignments are recorded per level, so adding depth 2 never re-asks depth 1.
  That is the frozen-scheme rule one level up.
- The join slice 03 exposes takes the level as a parameter, or resolves to the
  finest level that column has.

**What this slice must not do.** Build depth 2. Nothing has yet measured whether
depth 1 pays, and slice 05 is what answers that. A second level before the first
is measured is polishing past the bar.

One caution carried forward: granularity was unstable run to run at depth 1, and
a depth-2 scheme sitting under an unstable depth-1 scheme is unstable twice over.
Freezing the scheme handles it, provided the version covers the tree and not a
single level.

## Goal — the minimum testable behaviour

A category scheme for one column is frozen in configuration, every answered
value in that column is assigned against it, and the assignment lands on disk
where slice 03 can read it. A second run over an unchanged corpus and an
unchanged scheme re-assigns nothing.

## Why this slice exists

Slice 01 proves the categories are real: seven columns of twelve clear all five
conditions, and every category reaching five members draws on more than one
book, in twelve columns of twelve. It proves it on 400 held-out values per
column, and it writes nothing. A category a note cannot be looked up by cannot
be joined on. This slice turns the scheme into an assignment over a whole
column, and the assignment into a file.

## The scheme is frozen, and that is the point

Slice 01 measured the same prompt and the same model producing different
granularity between runs: `position` 5 categories then 15, `stops_holding` 7
then 20, `mechanism` 36 then 20. A vocabulary that reshuffles on every build is
not an index. Worse, reconciling one build's categories against the next one's
is name merging wearing a new coat, which is the cost this whole feature exists
to escape.

So stop rebuilding. Per cleared column the scheme is proposed once, read by a
person, and committed to `config/vocabulary.yaml`. After that the scheme is an
input, not an output. Assignment runs against it and only against it. A new
source's answers assign into the categories that already exist, at no cost to
any assignment already paid for, and no category id changes meaning under a note
already filed in it.

Changing a scheme becomes a deliberate, versioned act rather than a side effect
of running a command. The artifact records the scheme version it was built
against and refuses to serve assignments made against a different one.

## Start with one column

`mechanism` alone. 5,905 values, about 60 model calls, roughly $0.08 and twenty
minutes at twelve workers.

Assigning all seven cleared columns is 64,744 values, about 648 calls, roughly
$1 and about four hours. Affordable, but not yet earned: nothing has measured
whether the derived join improves retrieval at all, and slice 05 is what answers
that. `mechanism` is the sharpest column slice 01 read — 20 categories, the
largest holding 8.0%, every category crossing books — and one column is enough
for slice 03 to demonstrate the join and for slice 05 to compare the arms.

The command takes its column set as an argument, so widening to the other six is
a run, not a change.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a committed category scheme for `mechanism` in `config/vocabulary.yaml`
       and an answer store on disk with no assignment artifact yet
When   an operator runs `uv run axial vocabulary build --columns mechanism`
Then   an artifact is written under `data/vocabulary/` giving, for every
       answered value in that column, the category it was assigned or a
       recorded refusal
And    the artifact records the scheme version, the pin of the answers it was
       built from, and each category's member and distinct-source counts
When   the operator runs the same command again with the answers and the scheme
       both unchanged
Then   the run re-assigns nothing, makes zero model calls, and reports that it
       reused rather than rebuilt
When   the operator runs it again after one further source's answers land
Then   only the new values are assigned, and every assignment already on disk is
       byte-identical to what it was
```

- **Boundary / endpoint:** CLI — `uv run axial vocabulary build`
- **e2e test type:** CLI integration test against a temporary data directory
  with a stubbed model client that counts its own calls
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

- [ ] Every population entry lands with a category id or a recorded refusal,
      keyed by the note's `chunk_id`, its column, and the element's index within
      a list-valued answer. Slice 01's `PopulationEntry` already carries the
      value, the `chunk_id` and the `source_id`.
- [ ] A refusal is persisted as a refusal, distinct from a value that was never
      asked about. Slice 01 split `refused_count` from `unanswered_count` after
      review found the two lumped together; the artifact keeps that distinction
      rather than collapsing it again.
- [ ] A completed build has zero unanswered values. An unanswered value is a
      failed run, not a result, and the build says so rather than persisting a
      hole.
- [ ] The artifact records the scheme version it was built against.
- [ ] A build whose scheme version differs from the artifact's refuses, naming
      both versions, rather than mixing two schemes in one file.
- [ ] The pin is content-keyed over the rendered input, matching the convention
      merge and Gather already use: a change to the answers re-assigns, a change
      to an unrelated part of the repo does not.
- [ ] An unchanged pin and an unchanged scheme reuse the artifact and call the
      model zero times.
- [ ] New values assign incrementally. Assignments already on disk are neither
      re-asked nor rewritten.
- [ ] A column with no scheme in `config/vocabulary.yaml` fails naming the
      column, not with a stack trace and not with an empty success.
- [ ] A category carries a parent id, null at depth 1, and the scheme file parses
      a nested scheme even though the committed v1 scheme is flat.
- [ ] Assignments are recorded against the level they were made at, so a later
      level can be added without re-asking this one.

## Design notes for the executor

- **Reuse slice 01's assignment path.** `_assign_all`, `_assign_batch` and
  `_validate_assign_batch_keys` in `src/axial/vocabulary.py` already batch at
  100, validate that a response answers about the indexes it was asked about,
  and re-ask when it does not. That validation exists because its absence
  silently deflated the first corpus run's coverage — `mechanism` read 50.7%
  where the truth was 88.5%. Do not write a second assignment loop.
- **Follow the fit-persistence pattern already in the repo.** `axial.names` has
  `_write_fit_artifact` / `_read_fit_artifact` / `_manifest_reusable`, and
  `axial.argmap.build` mirrors it for bag state (#677). Mirror it a third time
  rather than inventing a fourth shape.
- **Content-keyed, like the decision logs.** Merge and Gather hash the
  *rendered* input, so a one-byte render change re-asks the corpus and a model
  change re-asks nothing. Same rule here, with the scheme version carried beside
  the pin: a scheme edit must re-assign, a model swap must not.
- **The scheme file is written by a person.** `config/vocabulary.yaml` holds,
  per cleared column, the category names and glosses taken from slice 01's
  report, plus a version string. Nothing in it is inferred at runtime. Slice 01
  prints the scheme; a person reads it and commits it. Which columns count as
  cleared is the founder's read of slice 01, never a rule in code.
- **No self-consistency check in this slice.** Slice 01 measured agreement
  between two models on a subsample, and the go/no-go rested on it. Re-checking
  every assignment here doubles the spend to re-measure a number already bought.
- **The label is the category's own name and gloss**, written by the model that
  proposed the scheme and approved by the person who committed it. There is no
  representative-member computation, because there is no clustering.
- **`data/vocabulary/` is gitignored like the rest of `data/`.** Build it in the
  main checkout. A worktree has no `data/`, so a build launched there would
  silently operate on nothing.

## Out of scope for this slice (deferred)

- Any retrieval tool reading the artifact. That is slice 03.
- Assigning the other six cleared columns. The command takes them as an
  argument; running it is a decision, not a code change.
- Re-proposing a scheme, and any automatic response to a scheme that fits the
  corpus badly. Slice 01 reports the fit; a person decides what to do about it.
- Merging categories, within a column or across columns.
- Rendering any of this into the vault.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Built on the real corpus** in `D:/axial`, on `mechanism`, with the second
      run observed to reuse rather than rebuild and a third run after new answers
      observed to assign only those. Log to
      `data/logs/<YYYY-MM-DD>-vocabulary-build/` with `run.jsonl`, `console.log`
      and `summary.md`; record the per-category member counts, the refusal count,
      the cost and the reuse observation.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Spec

This slice introduces a new persisted artifact under `data/vocabulary/` with its
own content-keyed pin, so it owes a spec section of its own rather than an
extension of an existing one. Write it in the same branch, beside
`specs/PHASE-B.md` §7.12, which owns the corpus-pin manifest this pin sits
alongside. The section states that the category scheme is configuration a person
commits, not a derived artifact, and why.

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification: centroid
  corrected to medoid, the cleared-column configuration given a declared home,
  and the owed spec section named.
- 2026-08-27 rewritten after slice 01 shipped, ran on the real corpus and
  rejected clustering. Clustering leaves this slice entirely; the scheme is
  frozen in configuration and assignment runs against it; scope is cut to
  `mechanism` alone until slice 05 says the join pays.
- 2026-08-28 founder ruling: the vocabulary is a tree. This slice still ships
  depth 1 only, but the artifact, the scheme file and the version must admit a
  second level without a migration, and a blob is now read as a category that
  wants splitting rather than as a column that failed.
