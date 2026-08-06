# smoke-v7 — the nine briefs on the redesigned retrieval

The first run on the post-#658 build. Nine briefs, one draw each: the six-brief
smoke set and the three authored eval questions, run as two concurrent sweeps,
exactly as smoke-v6 was.

**Code:** `f171d02` · **Corpus pin:** `sim-2026-07-30` (unchanged string; the
derived vault is NOT identical — see caveats) · **Result:** both sweeps exited 0,
`smoke: FAIL` on three cost-budget breaches and nothing else.

**Spend, $6.59 in total:** $2.569 the nine briefs · $0.662 a second draw of three
(§6) · $0.902 re-running the four records the papers stand on · $0.281 the two
papers (§7) · $2.167 the closed arm (§9) · gates, cents. The twelve-reviewer
panel (§8) carried no model bill.

```
axial brief smoke --briefs-dir config/briefs/smoke --sweep-dir data/runs/smoke-v7 --workers 6
axial brief smoke --briefs-dir config/briefs/eval  --sweep-dir data/runs/eval-v3  --workers 3
```

Before is smoke-v6 (`d8f5469`, 2026-08-01), preserved under `before/` before
anything ran. Rebuild the table with `python compare.py`.

**Every figure is provisional-on-sim (DEC-29).** This measures the engine, never
answer quality against a real academic question.

## What shipped between the two runs

#654 relational store · #656 intake fork · #658 retrieval walks notes, concepts
and opposition edges, names and dates become filters · #660 an answered fork no
longer ends the walk · #662 back matter is no longer retrievable evidence ·
#663/#664 the semantic residue resolver and its edges · **#574 raised
`evidence_char_budget` 100,000 → 250,000**.

## The comparison

| brief | legs | assembled | composed | cited | sources | claims | usd |
|---|---|---|---|---|---|---|---|
| P3-04 | **3/7 → 2/7** | 27 → 44 | 21 → 44 | 18 → 22 | 11 → 8 | 20 → 20 | 0.124 → 0.179 |
| S-01 | **3/3 → 2/3** | 63 → 98 | 18 → 49 | 10 → 15 | 10 → 10 | 14 → 13 | 0.137 → **0.363** |
| S-02 | **3/4 → 4/4** | 105 → 130 | 22 → 61 | 17 → 13 | 17 → 8 | 22 → 15 | 0.243 → 0.296 |
| S-03 | 3/3 → 3/3 | 62 → 57 | 21 → 50 | 10 → 11 | 5 → 4 | 18 → 12 | 0.154 → 0.183 |
| S-04 | 1/1 → 1/1 | 36 → 40 | 20 → 40 | 18 → 23 | 2 → 1 | 26 → 24 | 0.158 → **0.431** |
| S-05 | 1/1 → 1/1 | 57 → 50 | 21 → 50 | 13 → 24 | 1 → 1 | 8 → 32 | 0.151 → 0.265 |
| A | **5/6 → 3/6** | 373 → 203 | 18 → 53 | 11 → 11 | 9 → 3 | 22 → 17 | 0.170 → 0.234 |
| B | 3/4 → 3/4 | 29 → 128 | 23 → 56 | 17 → 18 | 7 → 5 | 26 → 21 | 0.144 → 0.243 |
| C | 7/8 → 7/8 | 117 → 78 | 23 → 59 | 18 → 28 | 17 → 12 | 25 → 29 | 0.149 → **0.375** |
| **total** | **29/37 → 26/37** | | | | | | **1.431 → 2.569** |

## 1. The oracle went down, net

Three briefs lost legs, one gained, five held. P3-04 (3/7 → 2/7), S-01 (3/3 →
2/3) and A (5/6 → 3/6) fell; S-02 reached 4/4 for the first time.

A is the largest single move and the one to look at first: assembled 373 → 203,
sources cited 9 → 3, and three legs missed — Mann's despotic/infrastructural
distinction, the critics of the state-formation literature, and the fierce-but-
weak Middle Eastern state.

## 2. B misses `elcheroth-2017` for the fifth time

The identity-production leg is unreached again, across three code versions and
two model arms. #658 was the change most likely to close it — a walk over
concepts and opposition edges rather than name pages alone — and it did not.
The standing finding stands.

## 3. The cost rise is #574's budget, not the walk

`evidence_char_budget` went 100,000 → 250,000 on 2026-08-02, after smoke-v6.
Composed notes rose 2–3x on every brief (18 → 49, 21 → 50, 22 → 61, 23 → 56,
23 → 59), synthesis prompts with it — B's was 491,502 chars — and cost followed:
$1.431 → $2.569 for the nine. Three briefs breached the $0.30 ceiling PR #548
cut from smoke-v4: S-01 $0.363, S-04 $0.431, C $0.375.

**The important part is the conjunction.** The model was shown 2–3x more evidence
and the required-source oracle still went down.

## 4. Sources cited fell while composed rose

S-02 17 → 8, A 9 → 3, C 17 → 12, P3-04 11 → 8. More notes in front of the model,
drawn from fewer books. On the argument-map path a drop in sources cited came
with better grounding (#572) and must not be read as a regression on its own —
whether that holds here is a question for the panel, not for this table.

## 5. The new tools are being used

`positions_on`, `opposition_pairs`, `who_argues_against`, `names_arguing_against`,
`name_neighbors` and `who_cites` appear across the set — every brief exercised at
least one edge-walking tool. #658 works mechanically. It is not paying off on the
oracle.

## 6. The second draw: A was variance, two losses reproduce

P3-04, S-01 and A re-run on the same code and pin, `data/runs/smoke-v7-draw2`,
$0.662, `smoke: PASS`.

| brief | smoke-v6 | v7 draw 1 | v7 draw 2 |
|---|---|---|---|
| A | 5/6 | 3/6 | **6/6** |
| P3-04 | 3/7 | 2/7 | **2/7** |
| S-01 | 3/3 | 2/3 | **2/3** |

**A's 5/6 → 3/6 was noise, and A's best score ever is on this build.** Its
sources cited went 3 → 8 between two draws of identical code, which makes that
column noisier than S-03's known 39% and retires "A regressed".

**P3-04 and S-01 reproduce, leg for leg** — the same missed legs both draws:
P3-04's five ANDed source ids, S-01's "European nation-state formation as the
setting". Two single-leg losses, each seen twice against a smoke-v6 single draw.

P3-04's loss should be weighted down separately: it is the last case on the flat
AND form, scoring against seven ANDed source ids, and smoke-v6 already called for
it to move to legs or be retired. One id's difference moves it a whole point.

## 7. The paper layer: both papers still pass, all four gates

The founder's addition — judge Axial's actual deliverable, not the intermediate
record. The two dev papers that met the release bar on 2026-08-02 were redrafted
with **the paper briefs untouched**: same thesis, same lens, same `analysis_ids`.
Only the four records beneath them were re-run on today's build ($0.902,
`data/runs/paper-records-v7`), which works because `brief_id` is content-keyed
and corpus-independent.

| paper | claims | new (b) | new (c) | words | sources | shape | confidence | usd |
|---|---|---|---|---|---|---|---|---|
| hollow-or-durable | 37 → 39 | 4 → 2 | 4 → 2 | 4,697 → 3,858 | 9 → **13** | strong → strong | low → low | 0.116 → **0.082** |
| the-long-arc | 52 → **66** | 3 → 3 | 6 → **7** | 6,350 → **8,358** | 11 → **15** | strong → strong | low → low | 0.155 → 0.199 |

A claim with `origin: null` is one the paper itself made; a claim carrying an
`origin` block was lifted from a record. That is the "new (b)/(c)" the 08-02 run
reported, and it is not the kind totals.

**All four Phase C gates pass on both, as on 08-02:**

| gate | metric | value |
|---|---|---|
| provenance-integrity | `provenance_completeness` | 1.0000 (n=215) |
| provenance-integrity | `confidence_upgrade_count` | 0 (n=105) |
| counter-position | `paper_counter_position_presence_rate` | 1.0000 (n=2) |
| paper-grounding | `b_claim_noncontradiction_rate` | 1.0000 (n=5) |
| paper-attribution-fidelity | `attribution_completeness` | 1.0000 (n=105) |
| paper-attribution-fidelity | `b_seam_mislabel_rate` | 0.0000 (n=32) |
| paper-attribution-fidelity | `c_seam_mislabel_rate` | 0.0000 (n=19) |

`trusted: True` on both. Both papers now cite more books than their 08-02
counterparts (9 → 13, 11 → 15), which runs opposite to the sources-cited drop at
record level in §4.

The two papers disagree about everything else. `the-long-arc` grew — 66 claims,
8,358 words, one more (c) — while `hollow-or-durable` shrank to 3,858 words and
halved its new (b) and (c) claims, at two thirds the cost. At one draw each,
neither direction is a finding. What the run establishes is narrower and is the
thing worth having: **the deliverable still clears the release bar on the
redesigned retrieval**, and the paper layer is now part of the smoke loop rather
than something measured once in August.

## 8. The panel: twelve sealed reviewers, and a positive control that caught everything

PHASE-B §9.4, run at N=3 per packet. Reviewers are Claude Code subagents with no
repository access; the seal hook allows exactly one staged packet per reviewer
and blocks every other path. Packets carry the rendered output plus the resolved
text of every passage its claims cite, and nothing else. No model bill.

**The positive control (property 6) passed, unanimously.** Three planted defects
went into a copy of `hollow-or-durable`: a fabricated survival cause cited to a
passage about Daraa governance, the war-as-erosion section replaced by "the
regime got lucky... it need not detain us", and a `high` band over coverage the
paper itself discloses as thin.

| | control | the same paper, clean |
|---|---|---|
| factual correctness | **weak ×3** | adequate ×3 |
| citation grounding | **weak ×3** | adequate ×3 |
| completeness | **weak ×3** | **strong ×3** |
| planted defects caught | **3 of 3, by all three** | — |

The panel discriminates, so the verdicts below are numbers rather than
impressions. This is the second live positive control in the project's history.

### The two papers

| paper | factual | grounding | completeness |
|---|---|---|---|
| Privilege and the Contracted-Out Militia | adequate ×3 | adequate ×3 | **strong ×3** |
| What the Mandate Built | **strong ×3** | strong ×1, adequate ×2 | **strong ×3** |

Spread is zero on seven of the eight cells, which is itself worth recording: P2-9
worried that one reviewer per packet made the bands a sorting rather than a
measurement, and at N=3 the bands are reproducible.

**Both papers' most-cited defect is the same citation.** Five of six reviewers
independently flagged a `bayat-2017` chunk that is a publisher's book-series
list — the line "Bassam Haddad, *Business Networks in Syria*" inside a catalogue
— used in both papers to tie Heydemann's networks-of-privilege framework to
Syria.

**And four reviewers reached the same diagnosis unprompted: the keystone Syrian
claim in both papers is carried by Moroccan and Egyptian evidence.** The corpus
holds no Syria-specific networks-of-privilege passage, so the drafter reaches for
the nearest thing and argues by analogy. That is a corpus gap presenting as a
citation defect, and no amount of retrieval work fixes it.

Two real defects the four automated gates do not see, both found by reviewers:
the rendered paper repeats a section heading verbatim, and its citation table
lists ids (`pc-009`–`pc-030`) that never appear as markers in the body.

## 9. Open against closed: a split decision, at 3.5x the price

Same corpus pin, same code, same briefs; the closed arm ran in its own process
with its own tier map (`AXIAL_SECRETS_PATH`), so neither arm could see the
other's config.

| | open | closed |
|---|---|---|
| intake / retrieval / counter-position | `deepseek-v4-pro`, `glm-5.2` | `openai/gpt-5.4` |
| synthesis | `glm-5.2` | `openai/gpt-5.6-sol` |
| **B** legs | **3/4** | 2/4 |
| **B** composed / cited / sources | 56 / 18 / 5 | **5** / 5 / 3 |
| **C** legs | 7/8 | **8/8** |
| **C** composed / cited / sources | 59 / 28 / 12 | 54 / 26 / 13 |
| spend, both briefs | **$0.618** | **$2.167** |

Six blind reviewers, three per brief, arm order flipped between B and C so no
judge could learn a position bias.

| brief | verdict | margins |
|---|---|---|
| **B** | **open, 3–0** | clear, clear, clear |
| **C** | **closed, 3–0** | narrow, narrow, clear |

**Nobody won the round.** Each arm took the brief it suited, and the reasons are
consistent across all six ballots:

- **B is a case question** — which account explains the Syrian pattern, tested
  against Syrian paramilitaries. The closed arm composed five notes, reached no
  Syrian evidence at all, and answered the paramilitary question with a Colombian
  example from a Kalyvas footnote. Every judge rated its grounding strong or
  impeccable and its completeness adequate or weak: rigorous about material that
  does not answer the question.
- **C is a survey question** — weigh four explanations and test the winner. The
  closed arm weighed all four; the open arm never engaged Wimmer's
  exclusion-as-legitimacy account, routing that competitor through Mann's
  narrower Dark Side thesis instead.

**The oracle and the panel agree, and this is the first time they have been
checked against each other.** C open scored 7/8 with "exclusion built into the
nation-state form" as its single missed leg. Two blind reviewers, with no access
to the case file, named the absence of Wimmer as the reason they preferred the
other arm. The mechanical instrument and the reader found the same hole.

So the practical reading is unchanged from 2026-07-31 and better evidenced: the
arms are close on quality, split by question type, and **the open arm costs 3.5x
less on the same two briefs**. Nothing here argues for moving the wiring.

One mechanical note: B on the closed arm failed `coverage_map_non_empty`, the
#490 empty-map check, which the open arm passes on every brief.

## Caveats that bound every number here

- **N = 1 per cell.** S-03 is known to move 39% between draws on unchanged code.
  S-01's 3/3 → 2/3 is a single leg and is inside that. A's 5/6 → 3/6 and
  P3-04's loss are larger, but neither is a second draw.
- **The vault is not identical.** The pin string is the hash of the raw sources
  and did not move, but #662 removed 497 notes (8.1%) of back matter from
  retrievable evidence between the runs, and #642/#646 re-materialized the name
  layer. Part of the sources-cited drop is that removal, not selection.
- **The oracle is comparable.** Case files and briefs are untouched since
  smoke-v6, and the only `run_report.py` change (#582) moved
  `retrieval_precision`'s denominator, not `retrieval_hit`.
- **Latency is not comparable to anything** — nine briefs on one machine across
  two concurrent sweeps.

## Next

1. **The net drop in §1 does not survive the second draw.** What survives is two
   reproducible single-leg losses (S-01, P3-04) and one brief that gained
   (S-02 3/4 → 4/4). S-01's is the one worth an issue; P3-04's oracle is the
   known-bad flat AND form.
2. **`evidence_char_budget` wants its own decision.** It tripled the bill and the
   oracle did not follow. That is a measurement, not yet a verdict.
3. ~~**The paper layer** over two record pairs.~~ **DONE, §7** — both papers pass
   all four gates on the redesigned retrieval.
4. **#665, #666 and #667 are closed not-planned** (founder decision, 2026-08-04:
   retrieval enhancement stops here). They live in `specs/PHASE-B.md` §8 as
   P2-10, P2-11 and P2-12, reopening under the DEC-55 rule.
5. **`axial brief smoke` stops at the record.** The paper step above was run by
   hand. If the deliverable is what the smoke loop should judge, that wiring is
   the slice — a future milestone, not now-work.
