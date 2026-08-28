# Feature: Values that repeat — a vocabulary derived from the corpus

Every note answers seventeen questions. Three of those columns hold values that
repeat often enough to join on, and only `names` is wired into anything. Twelve
columns hold answered values that are near-unique sentences: `mechanism` is
answered on 5,905 notes and every one of those answers is its own sentence.
Those columns are full, not empty. What they lack is repetition, so nothing
joins on them, and the name layer dominates retrieval by default. Names are the
one column where two passages literally share a string.

This feature makes the values repeat. Not by handing the model a menu of labels
to pick from, which was tried here and retired, but by deriving the categories
from the sentences the corpus already wrote and letting those be the vocabulary.

**How, decided by measurement on 2026-08-27, not by design.** The first
instrument clustered the sentences by embedding distance, reusing what
`axial.argmap.build` already does to `claim` text. Run on the real corpus it
gave 772 groups on `mechanism`, each a wording variant of its neighbours.
Embedding distance measures wording; the question here is meaning. It was
replaced by a model that reads 400 values, names the recurring kinds, and is
then tested on 400 values it has never seen. That named 20 categories on the
same column, and 88.5% of the unseen values fell into them.

- **Slug:** derived-vocabulary
- **Created:** 2026-08-27
- **Status:** 01, 02 and 04 done and closed; 03 corrected 2026-08-28 before building; 05 open
- **New system?** no
- **Project directory:** .

## The measured position this starts from

Distinct-value reuse per column over 6,860 notes in `data/answers/*.jsonl`,
excluding the `not-in-passage` abstention. Counted 2026-08-27, and re-derivable
for free by slice 01. It is the reason this feature exists and it is also the
trap: near-zero string reuse says nothing about whether the *meanings* repeat,
and the first instrument built here answered the string question with
embeddings and got a confident wrong answer.

| Column | Values | Distinct | Reuse | Shape |
|---|---|---|---|---|
| names | 163,255 | 70,616 | 56.7% | term |
| uses | 45,272 | 24,584 | 45.7% | term |
| position_of | 5,440 | 2,959 | 45.6% | degenerate |
| defines | 6,752 | 6,283 | 6.9% | term |
| ranges_over | 6,521 | 6,259 | 4.0% | sentence |
| about | 20,335 | 19,786 | 2.7% | sentence |
| arguing_against | 11,990 | 11,766 | 1.9% | sentence |
| stops_holding | 3,438 | 3,379 | 1.7% | sentence |
| move | 6,787 | 6,753 | 0.5% | sentence |
| assumes | 5,974 | 5,969 | 0.1% | sentence |
| position | 6,177 | 6,173 | 0.1% | sentence |
| claim | 6,698 | 6,697 | 0.0% | sentence |
| comparison | 6,106 | 6,106 | 0.0% | sentence |
| concedes | 6,064 | 6,064 | 0.0% | sentence |
| evidence | 6,852 | 6,852 | 0.0% | sentence |
| mechanism | 5,905 | 5,905 | 0.0% | sentence |

**Shape, not reuse rate, is what puts a column in scope.** `names`, `uses` and
`defines` hold short noun phrases: `nationalism`, `civil society`, `despotic
power`. Two passages using the same term write the same string, so those
columns already join and want folding rather than clustering. The twelve
sentence columns hold a written-out sentence per note. `defines` sits at 6.9%
and is out of scope; `ranges_over` sits at 4.0% and is in scope. Shape is the
distinction doing the work, not the four points between them.

`position_of` is neither: 950 of its 5,440 values are variants of "the author".

The twelve this feature targets are `about`, `claim`, `move`, `ranges_over`,
`stops_holding`, `position`, `arguing_against`, `mechanism`, `evidence`,
`comparison`, `concedes` and `assumes`. Ten sit under 6,900 values. `about` at
20,335 and `arguing_against` at 11,990 are the large ones, and slice 01 says
what it does about them.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| Issue | Slice | Goal (one line) | Status | PR |
|-------|-------|-----------------|--------|----|
| [#805](https://github.com/Muhanad-husn/axial/issues/805) | [the-sentence-columns-are-counted](01-the-sentence-columns-are-counted.md) | An operator can see, per sentence column, the categories a model named from reading a sample, and how many answers it never saw fall into them | ☑ **done**, read 2026-08-27 | [#815](https://github.com/Muhanad-husn/axial/pull/815) |
| [#806](https://github.com/Muhanad-husn/axial/issues/806) | [a-derived-vocabulary-is-persisted](02-a-derived-vocabulary-is-persisted.md) | A frozen category scheme in `config/vocabulary.yaml`, every `mechanism` value assigned against it, on disk, and a second run that re-assigns nothing | ☑ **done**, closed 2026-08-28 | [#817](https://github.com/Muhanad-husn/axial/pull/817) |
| [#807](https://github.com/Muhanad-husn/axial/issues/807) | [two-notes-meet-at-a-shared-group](03-two-notes-meet-at-a-shared-group.md) | A brief runs through `--arm map+vocab`, and two passages meet at a shared mechanism the way they meet at a shared name today | ☐ todo | — |
| [#808](https://github.com/Muhanad-husn/axial/issues/808) | [the-sweep-runs-the-map-arm](04-the-sweep-runs-the-map-arm.md) | `brief sweep --arm`, so the scored instrument can run whichever retrieval arm exists and records which one produced each draw | ☑ **done**, closed 2026-08-27 | [#818](https://github.com/Muhanad-husn/axial/pull/818) |
| [#809](https://github.com/Muhanad-husn/axial/issues/809) | [the-two-arms-are-compared](05-the-two-arms-are-compared.md) | `axial eval layers` reads three sweep directories and reports grounding and sources cited per arm, with each brief's draw spread | ☐ todo | — |

## Three arms, and the two questions they answer

Founder ruling, 2026-08-27, after review and independent verification both
found that an earlier draft of this plan measured neither the vocabulary it
builds nor anything that used it.

| Arm | Retrieval path | Exists |
|---|---|---|
| `name` | the name-layer loop | today |
| `map` | the argument map | today |
| `map+vocab` | the argument map plus the derived join, as a deterministic step in the map walk | slice 03 builds it |

- `name` against `map` asks whether the argument map beats the name layer.
- `map` against `map+vocab` asks whether the derived vocabulary adds anything.

The second is what this feature exists to answer. Slice 05 prints both
comparisons in one table and answers neither. The founder does.

**The derived join is a step in the map walk, not a tool offered to a model.**
Corrected 2026-08-28, before slice 03 was built. `run_map_ask_for_brief` is fully
deterministic after the door call — land, corridor, assemble — with no tool loop,
and `axial.answer.record` writes an honest empty trajectory for that arm. An
earlier draft of slice 03 gave the join a `ToolSpec`, edited
`src/axial/retrieve/dispatcher.py`, and asserted on a trajectory entry; none of
the three has any meaning on the arm it targeted. The join sits between the
corridor and assembly, and its audit trail is the record's `map_retrieval` block.
`src/axial/retrieve/` is not touched by this feature at all.

**What the whole feature costs.** Every figure below is measured or derived from
a measured one, and nothing here is a pass over the corpus.

| Slice | What it spends | Cost | Clock |
|---|---|---|---|
| 01 | 75 calls, all twelve columns, twice | $0.21 measured | ~20 min at 12 workers |
| 02 | assigning `mechanism`'s 5,905 values, ~60 calls | ~$0.08 | ~20 min at 12 workers |
| 02, widened | all seven cleared columns, 64,744 values, ~648 calls | ~$1 | ~4 hours |
| 03 | one brief run, plus a human reading categories | ~$0.04 | minutes |
| 04 | nothing | $0 | — |
| 05 | 5 briefs × 3 draws × 3 arms = 45 runs | ~$1.90 | ~2.5 h at 3 workers |

Slice 02's widened row is the only figure here that runs for hours, and it is
deliberately deferred behind slice 05: widening before the comparison says the
join pays would be buying reach nobody has shown is worth having.

## Slice 01 is a go/no-go, for slices 02 and 03 only

**Slices 02 and 03 were not committed work until 01's number was read.** If the
sentence columns had not grouped, there would be no derived vocabulary to build
on and neither slice would happen. That was a real possible outcome, and the
plan reached it cheaply: 01 cost $0.21 across two full runs.

**Slice 04 is not gated by it.** It depends on nothing here, and giving the
sweep an arm selector is useful whatever slice 01 reads. On a no-go, 04 and a
two-arm 05 would still run and still answer the first question, which never
depended on it.

The bar is written into slice 01 in advance: five numeric conditions on one
column, including a floor on cross-source categories, a ceiling on the largest
one, a floor on how much of a held-out sample is placed, and a floor on how far
a second, different model agrees. It deliberately does not require a majority
of the column's values to land in a large category. A majority test is passed
by a single blob and failed by forty real recurring mechanisms covering a third
of the column, which is the outcome this feature is hoping for.

**Read 2026-08-27: seven of twelve columns clear all five**
(`data/logs/2026-08-27-vocabulary-categorise-v2/`), and every category reaching
five members crosses books, in twelve columns of twelve, in both runs. That last
number is what the feature exists for and it is the most stable thing measured
here.

Two caveats stay attached to the go:

- `arguing_against` clears the agreement floor by 1.8 points at n=68 and
  `mechanism` by 1.4 at n=83, where the standard error is about 5.5. Those two
  passes sit inside their own noise on that one condition. The other five clear
  every condition with real margin.
- The granularity of a scheme is unstable run to run: `position` 5 categories
  then 15, `stops_holding` 7 then 20, `mechanism` 36 then 20. **Slice 02 answers
  this by freezing the scheme in `config/vocabulary.yaml` rather than deriving
  it on every build.** Reconciling one build's categories against the next one's
  would be name merging in a new coat, which is the cost this feature exists to
  escape.

**The five columns that failed all failed the same way**, on the ceiling over
the largest category: `comparison` at 50.5%, `concedes` 27.0%, `stops_holding`
25.5%, `assumes` 25.2%. Nothing failed for lack of structure. Founder ruling
2026-08-28: the vocabulary is a tree, and a blob is a category that wants
splitting rather than a column that failed. A second level over a blob is
slice 01's own instrument pointed at a subset, so it needs no new machinery and
costs about what the first level cost. Slice 02 ships depth 1 and must not
foreclose depth 2; building depth 2 waits on slice 05 saying depth 1 pays.

The first run (`data/logs/2026-08-27-vocabulary-categorise/`) is kept beside the
corrected one rather than overwritten. It read six of twelve, because a
silent-failure path in the assign loop counted a value the model never answered
about as a value the model refused. Both runs together are what says the
difference was the defect and not variance: `mechanism` 50.7% to 88.5%, `claim`
75.0% to 99.5%.

**The bar is cleared and the report has been read.** What remains is the
founder's word to start 02, and one scoping decision already written into that
slice: it assigns `mechanism` alone, for about $0.08 and twenty minutes, rather
than all seven cleared columns for about $1 and four hours. Nothing has yet
measured whether the derived join improves retrieval, so widening before slice
05 answers that would be paying for reach nobody has shown is worth having.

## Dependency order

01 → 02 → 03 → 05. 04 depends on nothing, and 05 needs it too.

**Nothing here is parallel-safe.** Every slice adds a subcommand or a flag to
`src/axial/cli.py`, a known hot file, and its tests to `src/axial/test_cli.py`.
`independence.mjs` refuses every pair on that basis. Build one at a time.

An earlier draft had 03 clear of `cli.py` and therefore parallel-safe with 04.
That stopped being true when 03 grew a real command boundary, which was the
right trade: the parallel pair was only usable after 02 merged anyway.

Recommended order: 01 alone, then stop and read its number. **Done 2026-08-27.**
Next is **02 on `mechanism` alone**, then 03, then 04 and 05 together.

## Out of scope (whole feature)

- **Removing the name layer.** This feature produces the number that decides
  its future. It does not act on it. Whatever slice 05 reports, retiring name
  pages is separate work, filed separately, after the founder rules.
- **Asking the model to pick from a closed vocabulary.** Retired here and
  staying retired: the off-list validator is gone, `config/domains/syria/schema.yaml`
  records D4/D9 striking it, the codebook records that rewriting the definitions
  bought no agreement gain (DEC-30), and `artifact_role` was struck after two
  runs disagreed on 48.5% of artifacts (#429). Every group here is derived from
  what the corpus already wrote.
- **Re-interrogating the corpus.** No slice re-asks a question or moves the
  corpus pin. Everything reads `data/answers/` as it stands.
- **`names`, `uses`, `defines` and `citations`.** The first three are
  term-shaped and want folding, not clustering. `names` already has a
  clustering and merge pass, and `uses` is filed as #811. `citations` holds
  structured records rather than sentences.
- **Tuning the argument map's own thresholds.** `BAG_DISTANCE_THRESHOLD = 0.55`
  stays where it is. Slice 01 does not cluster at all any more, and never
  touches the claim path already in production -- though its `claim` reading is
  the sharpest comparison available against what argmap's bagging produces:
  1,937 positions at 35.3% cross-source, against 10 categories at 100%.

## Vocabulary this plan borrows and does not define

"Rung-3 gates", "quorum-accuracy", and which of the four gates is the grounding
gate are defined in `specs/PHASE-B.md` and `src/axial/brief/sweep.py`. Slices 04
and 05 use them. Read them there.

Throughout, the figure slice 05 reports is **distinct sources cited** in a
brief's answers, not sources retrieved. Those are different quantities and the
decision turns on which.

## Two defects, filed separately

Found while counting. Neither belongs to this feature and both are their own
issue.

1. **[#810](https://github.com/Muhanad-husn/axial/issues/810), the literal
   string `"[]"` stored where an empty list belongs.** `arguing_against` 17,
   `defines` 15, `citations` 4, `uses` 2. Thirty-eight records. Slice 01
   excludes them from its population, so the census is unaffected. The records
   are still wrong.
2. **[#779](https://github.com/Muhanad-husn/axial/issues/779), a PDF glyph the
   extractor lets through.** Measured on 2026-08-27, after this feature was
   planned: `●` sits in 384 chunks across 2 of 35 sources, and only
   `batatu-1999`'s 209 are damage. It stands in there for an Arabic underdot
   consonant mid-word. `heydemann-2004`'s 175 are a legitimate running-header
   divider and must not be touched. Five answer records reproduce the glyph
   verbatim, all in `names`. The passage text is wrong for all 209 chunks, so
   the sentences this feature clusters were read from damaged text; the stored
   answers themselves largely are not affected.

   **A mojibake claim in an earlier draft of this README is withdrawn.** A
   corpus-wide scan for U+FFFD, double-encoded UTF-8 and control characters
   returned zero hits. The value that looked like mojibake was a correct
   em-dash, misread from terminal output.

## Disposition of #779: rewritten, not closed

Rewritten in place on 2026-08-27, keeping the number.

#779 bundled three jobs under a name-merge framing: kind variants, surface
pairs the fold never blocked, and extraction damage. The first two were work on
the layer this feature may demote and are withdrawn. The third is a live corpus
defect, and its census evidence in `data/reports/names-by-kind/` stays valid.

It is now filed as an extraction and normalization bug, with the name-merge
framing and the 300 fold-collision groups removed from the body. Closing it
would have thrown away the one finding in it that survives.

## Notes / open questions

- **`uses` is the largest unexploited column in the corpus.** 45,272 mentions,
  24,584 distinct, top values `nationalism` (266), `nation-state` (166),
  `civil society` (139). It already repeats as plain strings. Nothing folds it,
  merges it, pages it, or retrieves it. Filed as
  [#811](https://github.com/Muhanad-husn/axial/issues/811), and probably
  cheaper than this whole feature.
- **Spec sections.** Slice 01 owes none: it may kill the feature, and writing a
  section first is polishing past the bar. Slice 02 owes one, because it
  introduces a persisted artifact with its own content-keyed pin. Slices 03 to
  05 extend `specs/PHASE-B.md` §7.5 and §7.17 as they land.
