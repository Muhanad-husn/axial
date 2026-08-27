# Feature: Values that repeat — a vocabulary derived from the corpus

Every note answers seventeen questions. Three of those columns hold values that
repeat often enough to join on, and only `names` is wired into anything. Twelve
columns hold answered values that are near-unique sentences: `mechanism` is
answered on 5,905 notes and every one of those answers is its own sentence.
Those columns are full, not empty. What they lack is repetition, so nothing
joins on them, and the name layer dominates retrieval by default. Names are the
one column where two passages literally share a string.

This feature makes the values repeat. Not by handing the model a menu of labels
to pick from, which was tried here and retired, but by grouping the sentences
the corpus already wrote and letting the groups be the vocabulary. The
mechanism already exists and already works: `axial.argmap.build` clusters
passages by the cosine similarity of their `claim` text with a local encoder
and zero model calls. It runs on one column out of seventeen. Nobody has asked
whether the 5,905 mechanism sentences fall into forty recurring mechanisms.

- **Slug:** derived-vocabulary
- **Created:** 2026-08-27
- **Status:** filed and revised — #805, #806, #807, #808, #809
- **New system?** no
- **Project directory:** .

## The measured position this starts from

Distinct-value reuse per column over 6,860 notes in `data/answers/*.jsonl`,
excluding the `not-in-passage` abstention. Counted 2026-08-27, and re-derivable
for free by slice 01.

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
| [#805](https://github.com/Muhanad-husn/axial/issues/805) | [the-sentence-columns-are-counted](01-the-sentence-columns-are-counted.md) | An operator can see, per sentence column, how many groups its answers fall into, how much of the column they cover, and how many reach a second source | ☐ todo | — |
| [#806](https://github.com/Muhanad-husn/axial/issues/806) | [a-derived-vocabulary-is-persisted](02-a-derived-vocabulary-is-persisted.md) | The groups become an artifact on disk with a stable id and a medoid label, so anything downstream can read which group a note's answer belongs to | ☐ todo | — |
| [#807](https://github.com/Muhanad-husn/axial/issues/807) | [two-notes-meet-at-a-shared-group](03-two-notes-meet-at-a-shared-group.md) | A brief runs through `--arm map+vocab`, and two passages meet at a shared mechanism the way they meet at a shared name today | ☐ todo | — |
| [#808](https://github.com/Muhanad-husn/axial/issues/808) | [the-sweep-runs-the-map-arm](04-the-sweep-runs-the-map-arm.md) | `brief sweep --arm`, so the scored instrument can run whichever retrieval arm exists and records which one produced each draw | ☐ todo | — |
| [#809](https://github.com/Muhanad-husn/axial/issues/809) | [the-two-arms-are-compared](05-the-two-arms-are-compared.md) | `axial eval layers` reads three sweep directories and reports grounding and sources cited per arm, with each brief's draw spread | ☐ todo | — |

## Three arms, and the two questions they answer

Founder ruling, 2026-08-27, after review and independent verification both
found that an earlier draft of this plan measured neither the vocabulary it
builds nor anything that used it.

| Arm | Retrieval path | Exists |
|---|---|---|
| `name` | the name-layer loop | today |
| `map` | the argument map | today |
| `map+vocab` | the argument map plus the derived join | slice 03 builds it |

- `name` against `map` asks whether the argument map beats the name layer.
- `map` against `map+vocab` asks whether the derived vocabulary adds anything.

The second is what this feature exists to answer. Slice 05 prints both
comparisons in one table and answers neither. The founder does.

## Slice 01 is a go/no-go, for slices 02 and 03 only

**Slices 02 and 03 are not committed work until 01's number is read.** If the
sentence columns do not group, there is no derived vocabulary to build on and
neither slice happens. That is a real possible outcome, and the plan reaches it
cheaply: 01 costs machine time and nothing else.

**Slice 04 is not gated by it.** It depends on nothing here, and giving the
sweep an arm selector is useful whatever the census says. On a no-go, 04 and a
two-arm 05 still run and still answer the first question, which never depended
on the census.

The bar is written into slice 01 in advance: five conditions at one threshold,
including a floor on cross-source groups and a ceiling on the largest group. It
deliberately does not require a majority of the column's values to land in a
group. A majority test is passed by a single blob and failed by forty real
recurring mechanisms covering a third of the column, which is the outcome this
feature is hoping for.

Anyone executing this plan stops at the end of 01 and shows the founder the
report.

## Dependency order

01 → 02 → 03 → 05. 04 depends on nothing, and 05 needs it too.

**Nothing here is parallel-safe.** Every slice adds a subcommand or a flag to
`src/axial/cli.py`, a known hot file, and its tests to `src/axial/test_cli.py`.
`independence.mjs` refuses every pair on that basis. Build one at a time.

An earlier draft had 03 clear of `cli.py` and therefore parallel-safe with 04.
That stopped being true when 03 grew a real command boundary, which was the
right trade: the parallel pair was only usable after 02 merged anyway.

Recommended order: **01 alone, then stop and read its number.**

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
  stays where it is. Slice 01 sweeps thresholds for the new columns and reports
  what it finds, without touching the claim path already in production.

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
