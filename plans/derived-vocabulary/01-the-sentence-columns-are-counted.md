# Slice 01: The sentence columns are categorised

- **Feature:** derived-vocabulary
- **Issue:** [#805](https://github.com/Muhanad-husn/axial/issues/805)
- **Slice slug:** the-sentence-columns-are-counted
- **Branch:** feat/derived-vocabulary/01-the-sentence-columns-are-counted
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

> **Rewritten 2026-08-27, founder ruling.** The slice first shipped as a
> clustering census: group each column's sentences by embedding distance and
> count the groups. It was built, run on the corpus, and rejected. The founder's
> question was whether the values can be *categorised*, and embedding distance
> measures wording, not meaning. The measurement that settled it is in
> "Why this slice exists" below. The slug, branch and issue number are kept so
> the plan, the branch and the tracker still point at each other; the
> deliverable is new.

## Goal — the minimum testable behaviour

An operator runs one command and sees, for each of the twelve sentence-valued
answer columns: the categories a model named after reading a random sample of
that column's answers, how many answers from a second, disjoint sample it had
never seen fall into those categories, how many members and how many distinct
sources each category draws, and how far a second model agrees with the first
about where a value belongs. Roughly five model calls per column. No pipeline
artifact, no corpus pin moved.

## Why this slice exists

This is the go/no-go for the whole feature. The premise is that the sentences
in `mechanism`, `concedes` and the rest repeat in meaning even though they
never repeat as strings. Three instruments were measured against the same
`mechanism` column (5,871 answered values, 0% string reuse) on 2026-08-27:

| Instrument | Units produced | 5+ members | reaching 2+ books |
|---|---|---|---|
| MiniLM cosine clusters at 0.55 | 772 groups | 264 | 200 (75.8%) |
| argmap positions on `claim`, already on disk | 1,937 | 357 | 126 (35.3%) |
| a model reads 400 values and names categories | **14** | 14 | 14 (**100%**) |

The categorisation generalised: **70.8% of 400 values the model had never
seen** fell into a scheme derived from a disjoint 400, for **$0.026**. The
categories read like "Elite networks and clientelism" (25 members, 13 books)
and "Path dependence and institutional legacy" (18 members, 12 books).

Embedding distance measures wording, and it flatters itself while doing it. The
`about` column's largest cluster at 0.55 held 415 sentences whose only shared
feature was the word *Syrian* — "agricultural income of Syrian small farmers"
next to "Syrian video art as a critical alternative to sentimental
nationalism". A geometric group crosses books easily, because different books
use the same words about the same country; a shared *argument* crosses far less
often, which is why the honest instrument reports 35.3% cross-source on `claim`
where the geometric one reports 64.4%.

The repo already knew this. `axial.argmap.build` bags by wording and then
spends one model call per bag asking what argument recurs across passages that
"merely resemble each other" — the bagging is not the answer, it is the cheap
step before the answer. Bagging first is also what fragments argmap: 1,937
positions at a median size of 2, near the restatement failure its own prompt
warns about. Reading a random sample cold, with no bag, produced 14 general
categories instead.

## INVEST check

- **Independent:** reads `data/answers/` and writes only its own report and run
  log. Depends on no other slice. Slice 02 depends on it, both for the module
  and for the decision.
- **Valuable:** it produces the number that decides the feature, and the
  category schemes it names are the input slice 02 persists.
- **Small:** one module, one CLI subcommand, one report formatter, two prompts.
  `read_column` already exists from the first build and is kept unchanged.
- **Testable:** every unit behaviour is exercised with an injected fake client,
  the way `axial.argmap.build` and `axial.gather` already inject theirs, so no
  test makes a model call.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  an answer store on disk holding notes from more than one source, whose
       `mechanism` answers include several that say the same thing in different
       words and several that say unrelated things
And    a model client that names categories when asked to name them and assigns
       values to them when asked to assign
When   an operator runs `uv run axial vocabulary examine --columns mechanism`
Then   the report names `mechanism`, its answered-value count, its distinct-
       string count, and how many values were excluded as abstentions
And    it lists every category the model named, with its gloss, its member
       count and the number of distinct sources its members come from
And    it gives the share of the held-out sample that was assigned to some
       category, the number of categories with five or more members, how many
       of those span two or more sources, and the largest category's share
And    it gives the share of a subsample on which a second, different model
       agrees with the first about which category a value belongs to
And    it reports the model, the call count and the cost per column
And    the command writes nothing under `data/answers/`, `data/chunks/` or any
       other pipeline store
```

- **Boundary / endpoint:** CLI — `uv run axial vocabulary examine`
- **e2e test type:** CLI integration test (`src/axial/test_cli.py`), driving
  `build_parser`/`main` against a temporary answer store with an injected
  client, in the style of the existing `names examine` CLI tests
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

Four behaviours are already built and green; they are the population reader,
and they are kept as they stand.

- [x] Reading a named column from the answer store yields one value per note
      that answered it, with the note's `chunk_id` and `source_id` attached.
- [x] An abstention is excluded from the population, not categorised. Reuse
      `axial.query.reader.is_abstention` rather than re-deciding what an
      abstention is.
- [x] The literal string `"[]"` and an empty string are excluded on the same
      terms as an abstention, and the count of what was excluded is reported
      rather than silently dropped.
- [x] A list-valued column (`about`, `arguing_against`) contributes one
      population entry per list element, not one per note.

The rest is new.

- [ ] The proposal sample and the assignment sample are disjoint, drawn from a
      stated seed, so a re-run over the same corpus reads the same values.
- [ ] The assignment sample is held out: no value in it reaches the model that
      proposes the categories. This is the whole measurement, so a test asserts
      the two samples do not intersect rather than trusting the slicing.
- [ ] A model that returns roughly as many categories as it was shown answers
      has restated rather than categorised. The report flags that column as a
      failed proposal instead of reporting its numbers as a result.
- [ ] Assignment runs in batches, and a label the model returns that is not in
      the scheme counts as unassigned. A model may not invent a category at
      assignment time.
- [ ] The report gives the assignment rate over the held-out sample, per-
      category member and source counts, the largest category's share, and how
      many categories with five or more members span two or more sources.
- [ ] A second model assigns a subsample of the same held-out values against
      the same scheme, and the report gives the share of that subsample where
      the two models agree.
- [ ] A column whose population is smaller than the two samples together is
      measured on what it has, and the report says the samples were reduced.
- [ ] The command makes no write under any pipeline store.

## Design notes for the executor

- **Keep `read_column`, drop the rest.** `src/axial/vocabulary.py` on this
  branch already has the population reader and it is right. Delete the
  threshold sweep, the linkage, the encoder import, the sampling ceiling and
  the top-groups print. Both hand-picked constants go with them
  (`SAMPLE_CEILING = 6_860` and the 0.35–0.75 threshold spread), which is the
  over-engineering tripwire closing on its own.
- **Propose, then assign held-out. Never score the proposal sample.** A scheme
  always fits the values it was derived from. The only number worth reporting
  is the rate on values the model has not seen.
- **Two prompts, and the anti-restatement rule belongs in both.** A category is
  a kind of thing, not a topic; two answers that sit together only because they
  name the same country, person or period are not one category; returning few
  or no categories is a real and acceptable answer. `axial.argmap.build`'s
  position prompt already carries this rule and is the model to follow.
- **The second model is the check on self-consistency.** The same model
  proposing and assigning grades its own work. A different model assigning a
  subsample against the same scheme is what makes the assignment rate mean
  something. Take it from the pipeline config's existing pass wiring; do not
  hard-code a model id.
- **Sample sizes are arguments with defaults, not constants.** 400 and 400
  measured at $0.026 for one column; the parser states them in `--help` because
  the bar quantifies over them.
- **`--columns` defaults to all twelve**, named explicitly in the module, since
  `about` and `arguing_against` are list-valued and still belong.
- **The run log is the operator's, not the command's.** The command prints a
  report and writes no pipeline artifact.

## Out of scope for this slice (deferred)

- Assigning a whole column. This slice assigns a held-out sample to decide
  whether the scheme holds; assigning all 5,871 values of `mechanism` and
  keeping the result is slice 02, and that is where the corpus-scale spend
  belongs — an assignment this slice makes is thrown away by design.
- Persisting anything: no artifact, no category ids on disk, no reuse across
  runs.
- A second round over the values that fit nothing.
- `names`, `uses`, `defines`, `citations`, `position_of`.
- Changing `BAG_DISTANCE_THRESHOLD` or anything else in the live claim path.

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
five numeric conditions hold for at least one of the twelve columns, and the
founder's read agrees:

1. **At least 8 categories with 5 or more members** in the held-out sample.
   Sets a floor on how much recurring structure was found. The `mechanism`
   probe gave 14 categories, every one of them at 5 or more.
2. **The largest category holds under 25% of the assigned sample.** Rules out
   the blob. Fourteen even categories would be 7% each; the probe's largest was
   10.8%. A quarter of the column in one category is a category doing no work.
3. **At least half of those categories draw members from more than one source.**
   A category that is one book talking to itself joins nothing, and the recorded
   finding that only 40.5% of argument-map edges reach another book makes
   single-source groups the expected case rather than a corner one. The probe
   reached 100%.
4. **At least half of the held-out sample is assigned to some category.** The
   probe reached 70.8%. Below half, most of the column joins nothing and the
   scheme is not a vocabulary.
5. **A second model agrees with the first on at least 60% of the subsample
   entries the first model actually assigned to a category** (`agreement_
   where_assigned_rate`, with its own `n` reported alongside it) -- not the
   overall agreement rate, which also counts two models that both fail to
   place a value as "agreeing" about it, and on the measured `mechanism`
   probe that shared-silence agreement alone was worth roughly 29 points
   (29.2% of the held-out sample went unassigned). Without the restriction
   the condition is passable without the two models ever agreeing about a
   single category. This condition did not exist in the probe and is the
   one genuinely open question the probe left.
6. **The founder reads the category names and glosses, and at least 7 of the 10
   largest are legible as one recurring kind of thing.**

Note what this bar deliberately does **not** require: that a column's values
mostly fall into large categories. Fourteen real recurring mechanisms covering
70% of the sentences, with the rest genuinely one-off, is a usable cross-source
join and exactly what slice 03 needs.

If no column clears the bar, slices 02 and 03 do not happen. Slice 04 is
unaffected: it depends on nothing here and is useful whatever this says.

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification: the bar was
  replaced (a majority test was passable by a blob and failable by the plan's
  own hypothesis), cross-source span added to the report, sampling permitted
  above the ceiling with the sample size printed, and the "writes no file"
  contradiction against the run-log requirement resolved.
- 2026-08-27 built as a clustering census, run on the full corpus, and
  rejected. Wording similarity is not categorisation, and the run's own output
  proved it: 415 sentences grouped on the word "Syrian". See
  `data/logs/2026-08-27-vocabulary-census/`.
- 2026-08-27 rewritten to the categorisation pass on the founder's ruling. The
  population reader survives; the clustering does not.
