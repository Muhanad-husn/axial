# Feature: Values that repeat — a vocabulary derived from the corpus

Every note answers seventeen questions. Three of those columns hold values that
repeat often enough to join on — `names`, `uses`, `defines` — and only `names`
is wired into anything. Twelve columns hold roughly six thousand answered
values each that are near-unique sentences. Those columns are full, not empty:
`mechanism` is answered on 5,905 notes and every one of those answers is its
own sentence. Nothing joins on them, because nothing repeats, and so the name
layer dominates retrieval by default — names are the one column where two
passages literally share a string.

This feature makes the values repeat. Not by handing the model a menu of labels
to pick from, which was tried here and retired, but by grouping the sentences
the corpus already wrote and letting the groups be the vocabulary. The
mechanism already exists and already works: `axial.argmap.build` clusters
passages by the cosine similarity of their `claim` text with a local encoder
and zero model calls. It runs on one column out of seventeen. Nobody has ever
asked whether the 5,905 mechanism sentences fall into forty recurring
mechanisms.

- **Slug:** derived-vocabulary
- **Created:** 2026-08-27
- **Status:** filed — #805, #806, #807, #808, #809
- **New system?** no
- **Project directory:** .

## The measured position this starts from

Distinct-value reuse per column over 6,860 notes in `data/answers/*.jsonl`,
excluding the `not-in-passage` abstention. Counted 2026-08-27; re-derivable for
free by slice 01.

| Column | Values | Distinct | Reuse |
|---|---|---|---|
| names | 163,255 | 70,616 | 56.7% |
| uses | 45,272 | 24,584 | 45.7% |
| position_of | 5,440 | 2,959 | 45.6% |
| defines | 6,752 | 6,283 | 6.9% |
| ranges_over | 6,521 | 6,259 | 4.0% |
| about | 20,335 | 19,786 | 2.7% |
| arguing_against | 11,990 | 11,766 | 1.9% |
| stops_holding | 3,438 | 3,379 | 1.7% |
| move | 6,787 | 6,753 | 0.5% |
| assumes | 5,974 | 5,969 | 0.1% |
| position | 6,177 | 6,173 | 0.1% |
| claim | 6,698 | 6,697 | 0.0% |
| comparison | 6,106 | 6,106 | 0.0% |
| concedes | 6,064 | 6,064 | 0.0% |
| evidence | 6,852 | 6,852 | 0.0% |
| mechanism | 5,905 | 5,905 | 0.0% |

`position_of`'s 45.6% is not a vocabulary — 950 of its 5,440 values are
variants of "the author". The twelve sentence columns this feature targets are
`about`, `claim`, `move`, `ranges_over`, `stops_holding`, `position`,
`arguing_against`, `mechanism`, `evidence`, `comparison`, `concedes` and
`assumes`.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| Issue | Slice | Goal (one line) | Status | PR |
|-------|-------|-----------------|--------|----|
| [#805](https://github.com/Muhanad-husn/axial/issues/805) | [the-sentence-columns-are-counted](01-the-sentence-columns-are-counted.md) | An operator can see, per sentence column, how many groups its answers fall into and how much of the column those groups cover — for free, with no model call | ☐ todo | — |
| [#806](https://github.com/Muhanad-husn/axial/issues/806) | [a-derived-vocabulary-is-persisted](02-a-derived-vocabulary-is-persisted.md) | The groups become an artifact on disk with a stable id and a representative label per group, so anything downstream can read which group a note's answer belongs to | ☐ todo | — |
| [#807](https://github.com/Muhanad-husn/axial/issues/807) | [two-notes-meet-at-a-shared-group](03-two-notes-meet-at-a-shared-group.md) | Retrieval can ask for the notes that share a mechanism, a concession or an assumption with a given note, across sources — the job a name page does today | ☐ todo | — |
| [#808](https://github.com/Muhanad-husn/axial/issues/808) | [the-sweep-runs-the-map-arm](04-the-sweep-runs-the-map-arm.md) | `brief sweep` accepts `--map`, so the scored instrument can run the argument-map arm that `run` and `smoke` already accept | ☐ todo | — |
| [#809](https://github.com/Muhanad-husn/axial/issues/809) | [the-two-arms-are-compared](05-the-two-arms-are-compared.md) | One command reads two sweep directories and reports grounding and sources reached per arm, so the name layer's fate is decided on a number | ☐ todo | — |

## Slice 01 is a go/no-go

**Nothing after 01 is committed work until 01's number is read.** If the
sentence columns do not group — if `mechanism` yields 5,700 groups over 5,905
sentences at every threshold — then there is no derived vocabulary to build on
and slices 02 through 05 do not happen. That is a real possible outcome, and
the plan is built to reach it cheaply: 01 costs machine time and nothing else.

The reading that lets 02 proceed is stated in 01. Anyone executing this plan
stops at the end of 01 and shows the founder the report.

## Dependency order

Chain: 01 → 02 → 03, then 05 needs 03 and 04. 04 depends on nothing.

**Only one pair can be built at the same time: 03 and 04.** `independence.mjs`
over all five returns 18 findings. Four of the five — 01, 02, 04, 05 — add a
subcommand or a flag to `src/axial/cli.py` and its tests to
`src/axial/test_cli.py`, and collide there whatever their other paths say;
`cli.py` is a known hot file here. Slice 03 is the exception: it touches
`src/axial/retrieve/` and `src/axial/query/` and never `cli.py`, so the checker
clears 03 with 01 and 03 with 04.

**03 + 01 is a false green.** The checker sees no direct dependency because 03
declares `depends-on: 02`, and 02 is not in that pair. Transitively 03 cannot
start until 02 has merged, which cannot start until 01 has. Only 03 + 04 is
usable in practice, and only once 02 is in.

Recommended order: **01 alone, then stop and read its number.** It is the
go/no-go, it is free, and everything else is wasted if it fails. On a go: 02,
then 03 and 04 in parallel, then 05.

## Out of scope (whole feature)

- **Removing the name layer.** This feature produces the number that decides
  the name layer's future. It does not act on it. Whatever 05 reports, ripping
  out name pages is separate work, filed separately, after the founder rules.
- **Asking the model to pick from a closed vocabulary.** Retired here and
  staying retired: the off-list validator is gone, `config/domains/syria/schema.yaml`
  records D4/D9 striking it, the codebook records that rewriting the definitions
  bought no agreement gain (DEC-30), and `artifact_role` was struck after two
  runs disagreed on 48.5% of artifacts (#429). Every group in this feature is
  derived from what the corpus already wrote.
- **Re-interrogating the corpus.** No slice re-asks a question or moves the
  corpus pin. Everything here reads `data/answers/` as it stands.
- **`names`, `uses`, `defines` and `citations`.** `names` already has a
  clustering and merge pass. `uses` and `defines` already repeat and want a
  different treatment — see the notes. `citations` holds structured records,
  not sentences.
- **Tuning the argument map's own thresholds.** `BAG_DISTANCE_THRESHOLD = 0.55`
  stays where it is. Slice 01 sweeps thresholds for the *new* columns and
  reports what it finds, without touching the claim path already in production.

## Two defects, filed separately

Found while counting. Both are real, neither belongs to this feature, and both
are now their own issue.

1. **[#810](https://github.com/Muhanad-husn/axial/issues/810) — the literal string `"[]"` is stored where an empty list belongs** —
   `arguing_against` 17, `defines` 15, `citations` 4, `uses` 2. Thirty-eight
   records across the corpus. Small, mechanical, and it will silently become a
   one-member group in slice 01 if nobody fixes it.
2. **[#779](https://github.com/Muhanad-husn/axial/issues/779) — extraction damage inside stored values** — a `●` glyph inside names
   (`A ● hmad Jibr il`, `al-Wa ● tan-ul-ʿ Arab i`) and mojibake inside
   `comparison` values. This is a PDF glyph the extractor let through, and it
   sits in the passage text rather than only in the name — which means it
   corrupts every answer drawn from that passage, including the sentences this
   feature wants to cluster. It matters more under this direction, not less.

## Disposition of #779 — rewritten, not closed

**Rewritten in place on 2026-08-27**, keeping the number. Not superseded, not "not planned".

#779 bundled three jobs under a name-merge framing: kind variants, surface
pairs the fold never blocked, and extraction damage. The first two were work on
the layer this feature may demote and are withdrawn. The third is a live corpus
defect that gets worse under the new direction, and its census evidence in
`data/reports/names-by-kind/` stays valid.

It is now filed as an extraction and normalization bug — the `●` glyph and the
interior-space damage — with the name-merge framing and the 300 fold-collision
groups removed from the body entirely. Closing it would have thrown away the one
finding in it that survives.

## Notes / open questions

- **`uses` is the largest unexploited column in the corpus.** 45,272 mentions,
  24,584 distinct, top values `nationalism` (266), `nation-state` (166),
  `civil society` (139). It already repeats. Nothing folds it, nothing merges
  it, nothing gives it a page, and no retrieval tool reads it. That is a
  separate feature and probably a cheaper one than this. Filed as
  [#811](https://github.com/Muhanad-husn/axial/issues/811).
- Slice 01's biggest column is `about` at 20,335 values. Agglomerative
  clustering is O(n²) in the pairwise distances, and the proven size in this
  repo is `bag_passages` over 6,860 passages. 20,335 is nine times the pairs.
  Slice 01 handles this by reporting a column as deferred with its size, never
  by sampling it silently.
