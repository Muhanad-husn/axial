# #650 — retrieval over the relations: the paired live bar

2026-08-04. Old surface = `main` @ `31abb23`, run from `D:/axial`. New surface =
`feat/650-relational-retrieval` (PR #658), run from the worktree with the live
`data/` junctioned and writes going to the worktree's own `data/analyses`.
Questions: the standing hard set, `config/briefs/eval/` A, B and C. Model wiring
unchanged in both arms.

Three new-arm rounds were run, because the first two rounds each exposed a defect
worth fixing before judging. Only round 3 is the result; rounds 1 and 2 are kept
because their numbers are what located the defects.

| | commit | what changed |
|---|---|---|
| round 1 | `a7a84b3` | the four tools as first built |
| round 2 | `bb7090c` | name arguments resolve through `find_names`' tiers |
| round 3 | `bd80325` | a relational call's resolved name is a queried name |

## Bottom line

The redesign does what DEC-62 asked and the answers are no worse. The measured
wins are structural, not qualitative: the opposition edges are reachable at all
for the first time, two relations can be chained in one query, and the model
stops entering through the name pages. Blind quality came out a wash — 9 defects
against 11, one clear win, two narrow losses with named causes.

## 1. The retrieval surface actually moved

| | old | new (round 3) |
|---|---|---|
| door-tool calls | 39 | **4** |
| relation-tool calls | 0 | **28** |
| steps returning zero | 1 of 42 | **0** |
| composed notes | 139 | 128 |
| sources cited | 27 | 26 |
| cost, 3 briefs | $0.637 | $0.587 |

The door tools were not deleted and still answer; they stopped being the way in.

## 2. What the two intermediate rounds cost and bought

**Round 1 — `about` only matched an exact canonical.** 25 of 42 steps returned
zero against 1 of 42 on the old surface. `nationalism` → 158 notes;
`nationalism and war` → 0. `Charles Tilly` → 154; `Tilly war state formation
bellicist` → 0. Brief B asked `violence against civilians Syria` six times in a
row and four `sectarian*` variants after that, and degraded materially: 19
composed notes against 34, 4 sources cited against 8, confidence `not_measured`.

Fixed at the resolver, never in the loop's memory — #633 measured "you already
asked this" notes and repeats rose 14% → 20%. Round 2: **zero-result steps went
to 0** and brief B began halting on its own at 7 steps.

**Round 2 — the coverage map collapsed.** `names_queried` was fed only by the
door tools, so the per-name coverage map (§7.7) emptied out as the run stopped
using them: 11 entries → 2 on A, 8 → 1 on C, 5 → 0 on B. Brief B reported
`not_measured` after composing 23 notes and making 18 claims; brief C reported
`high` off a single name, which is a thinner measurement than the old arm's
`medium` over eight, not a stronger one.

Round 3 restores it — 8 / 5 / 6 entries against the old surface's 11 / 5 / 8 —
and the bands become honest: `medium` / `low` / `low`. Brief C's fall from
`medium` to `low` was predicted before the run and is the first truthful reading
of the three.

## 3. Blind judged result

Six sealed packets, arm-interleaved so the packet number carries no arm, one
independent reviewer each, none with any context beyond the packet. Key:
`packet-key.json`. Bands are factual correctness / citation grounding /
completeness.

| brief | old | new |
|---|---|---|
| A | strong / strong / strong · 4 defects | strong / strong / **adequate** · 3 |
| B | **adequate / adequate / adequate** · 5 defects | **strong / strong / strong** · 4 |
| C | strong / strong / strong · 2 defects | **adequate** / strong / strong · 2 |

**Brief B reproduces #572's finding independently.** The new arm cited 5 sources
against 8 and made 15 claims against 25 — on counts, the worst of the six. Blind,
it was the best. The old arm's extra sources produced its defects: two claims
enlisted Üngör and Vignal against Kalyvas when both cite Kalyvas approvingly, and
one claim is contradicted by its own passage. A drop in sources cited is still
not a regression.

**The two losses each have a named cause.** A's completeness fell only because
the counter-position failed to generate (§4 below); the judge called it evasive
and noted the cited chunk is present in the evidence, so it read as a system gap
rather than missing material. C's factual correctness fell on two misattributions
of one kind: chapters of the edited Heydemann 2000 volume credited to the editor
rather than to Sayigh and al-Khafaji.

**The built-in panel was run first and is not quotable.** `axial panel run`
self-reported `trusted: False` on the old arm: of three planted defects its
positive control caught none of two (`mis_grounded` 0/3 reviewers,
`strawman_counter_position` 0/3). Its reviewers run on the flash tier, all three
from one vendor. `config/pipeline.yaml` already documents the same tier failing
the `retrieve` pass — "the flash tier could not make it" — and never routed
`panel_review` off it. Pre-existing, not introduced here, not fixed here.
Verdicts in `console-judge.log`; no number from it is used above.

## 4. Open, and not caused by this change

Brief A's counter-position failed validation on the new arm: it cited
`mann-v2-1993-ec759675dcbd_184`, which is not a vault id. Traced — no tool ever
returned that string. It is a truncation of a real retrieved id,
`…_184_realist-theories-of-the-great-war_004`, mangled by the synthesis model
while writing. No claim is affected; only the counter-position. The validator
caught it and marked it failed rather than letting it through, which is the
guardrail working. One occurrence in three briefs, in a subsystem this issue did
not touch. It cost brief A a completeness band, so it is worth its own fix and
its own measurement.

## 5. Caveats that bound every number here

- **n = 1 per cell.** Between rounds 2 and 3 brief B moved 23 → 28 composed,
  18 → 15 claims, 8 → 5 sources, and the only code change between them was a
  recording change that cannot touch retrieval. Differences of that size are
  inside run-to-run variance; no per-brief win or loss is claimed from counts
  alone, which is why the blind judging is the result and the counts are not.
- **One reviewer per packet**, not three. Cross-arm band differences of one step
  are weak evidence on their own; the defect lists are the stronger signal.
- **`denominator_by_name` flips from empty to populated** on relational runs, so
  `usage_ratio` and `available_share` are not comparable between round 2 and
  round 3 records.
- Sim corpus, so every figure is provisional forever.

## Files

- `round1-new/`, `round2-new/`, `round3-new/` — new-arm records per round.
- `judge-old/`, `judge-new/` — the six records that were judged.
- `packet-key.json` — which packet was which arm.
- `console-old.log`, `console-new-round2.log`, `console-new-round3.log`,
  `console-judge.log`.
- `before-analyses/` — `data/analyses` as it stood before any run here.
- `compare_650.py` — the comparison script that produced the tables.
