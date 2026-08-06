# #649 intake fork-check: the live bar, part 1 and part 3

2026-08-04. Branch `feat/649-intake-forks` @ `87a3df1` (PR #656), run from the
worktree with the live `data/` junctioned in read-only; writes went to the
worktree's own `data/analyses`. Two `fork_check` calls,
`deepseek/deepseek-v4-flash`, ~6.5k prompt tokens total. Raw output:
`fork-probe.json`.

## What was run

`measure_question` + `assess_fork` on two briefs — no full analysis run, so
part 2 of the bar (does the answer change the evidence set) is NOT measured.

| | case / request | fork asked? |
|---|---|---|
| witness | Syria, 2011-2024 — did the civil war change the sources of regime durability, or expose ones already there? | yes, one |
| control | Nationalism — print capitalism and national consciousness | **no** |

## Bar part 3: PASS

The control question resolved 13 concepts, `is_fork=False`, no question asked,
34 completion tokens. Nothing is asked when there is no fork.

## Bar part 1: FAIL — a question is asked, but not about the measured imbalance

The question the fork-check produced:

> The concept 'authoritarian durability' has only 1 note, from a single source
> (bayat-2017). Do you want to treat that source as a full voice, or exclude it
> and rely on adjacent concepts (e.g. 'Assad regime') for evidence on regime
> durability?

Two defects, both visible in the measurement it was given.

**1. A 1-note concept was picked as the fork, and one option drops its only
source.** `authoritarian durability` is one note from one book. `top_share`
is 1.0 there for the trivial reason that n=1. The real measured imbalance in
this case is temporal and sits in the biggest concepts: `Syria` is 962 notes
across 22 sources whose mass is pre-war (Beshara 2011 202, Batatu 1999 140,
Heydemann 2000 127, Ayubi 1995 88) against Vignal 2021's 119, and
`Assad regime` is 49 notes of which **77.6% are Vignal 2021**. That is the
imbalance the bar names, and it was never surfaced. Neither temporal kind
(`temporal_role`, `temporal_consequence`) fired on what is, by DEC-62's own
wording, a consequence question.

**Offering to drop the only source on a concept also inverts DEC-62** — dates
and sources assign roles, not cutoffs; exclusion is the analyst's explicit
choice, never one of two symmetric defaults.

**2. The measurement is noise-dominated: 5 of 11 resolved concepts are junk.**
`find_names(word, limit=1)` per content word resolves stopword-ish tokens to
whatever page happens to contain them:

| word | door it resolved to |
|---|---|
| `Did` | *Brett Kavanaugh Fit in with the Privileged Kids. She Did Not* |
| `war` | Cold War (not the Syrian civil war) |
| `change` | Climate Change — 94.7% one Mann volume |
| `there?` | *Why Is There No Socialism in the United States?* |
| `2024` | late 2023 |

The control brief shows the same pattern (`corpus` → Habeas corpus, `say` →
`sa'y`, `about` → about 200 B.C.). This is the door-slate finding again
(`find-names-door-slate-not-similarity`): a single word matched inside a long
canonical is not a door onto the question.

## What has to change

- Resolve the question's **phrases**, not every content word, and drop a hit
  whose match is one word inside a much longer canonical.
- A fork must rest on a concept the corpus actually holds. A concept with one
  note is not a fork; it is a silence, and the disclosure already has a place
  to say so.
- Never offer dropping the only source on a concept as an option.
- The temporal shapes need to fire on the case DEC-62 wrote them for. The
  year data is in the measurement and was not used.

Part 2 was not run: measuring what an answer does to the evidence set is
premature while the fork itself is the wrong one.

## Also: CI

`tests/analysis/test_brief_run_analysis_record.py` fails on the new
`fork_answer` key — the test asserts the record's `brief` block exactly. One
key to add.

---

# Round 2 — `805942a`, after the phrase-resolution fix

`fork-probe-2.json`, same two briefs, same two calls.

## Bar part 1: PASS

The witness case now asks one question, and it is the measured imbalance:

> Vignal's 2021 study (38 of 49 notes) dominates the 'regime' concept, but the
> question asks whether the civil war changed sources of regime durability that
> were already there. Should we read Vignal as a post-war witness to pre-war
> roots, or exclude it to foreground pre-war structural sources (Heydemann
> 2000, Batatu 1999, Ayubi 1995)?

`concept='Assad regime'`, `kind='temporal_role'` — DEC-62's own shape. The
default option keeps every source and assigns roles; exclusion is the explicit
second choice, not a symmetric default. The junk doors are gone: the noise
words now land in `silent_terms` (`2024`, `expose`, `already`, `Did`,
`durability`) instead of resolving to *Brett Kavanaugh…* or Climate Change.

## Bar part 3: PASS

Control question: 28 completion tokens, `is_fork=False`, nothing asked.

## Bar part 2: NOT MEASURED — the run died on the fork-check

Arm A (unconstrained) aborted after interrogation, inside the fork-check:

```
ForkCheckParseError: drop_source_ids names 'hey demann-2000-66701ffbb36c',
not a real source of 'Syria''s own measurement
```

The model retyped `heydemann-2000-66701ffbb36c` with a space in it. The parser
is right to reject it — but two things are wrong behind that:

1. **The model is made to retype a source id at all.** A 24-char opaque id
   copied by hand into JSON is a mistyping waiting to happen, and it did, on
   the third call. The measurement already numbers its sources; an option
   should name an index the wrapper resolves, so the class of error stops
   existing.
2. **An advisory pre-pass kills a paid run.** The fork-check is optional by
   construction — no fork means nothing is asked and the run proceeds. A
   malformed answer should land in the same place (unconstrained, disclosed
   in `intake_fork`), not raise through `run_brief` and discard the
   interrogation already paid for.

Intermittent, not deterministic: the two probe calls before this one returned
well-formed ids.

---

# Round 3 — `2085b05`, bar part 2

Four full runs, `$1.05` total. The fork is assessed once and pinned across
both arms (`fork_effect.py`), so the arms differ only in the analyst's answer
— a fork-check is a model call and asked about `Civil War` in one run and
`Assad regime` in the next, which is fine for the product and useless for an
A/B.

Pinned fork: `Assad regime`, `temporal_role`, 78% Vignal 2021. Arm B answers
with the constraining option, `"Focus on pre-war roots: drop Vignal (2021) as
post-war voice"`.

| | arm A (unanswered) | arm B (answered) |
|---|---|---|
| assembled notes | 63 | **0** |
| composed notes | 56 | **0** |
| sources in evidence | 7 | **0** |
| claims written | 17 | 5, all with zero grounds |
| retrieval turns used | full walk | **halted at 3 of 14** |
| `intake_fork.effect` | — | `notes_before: 0, notes_after: 0` |

## FAIL — the answered arm collapses to no evidence at all

The bar asks that the analyst's answer demonstrably change the evidence set.
It changes it to nothing.

`effect` reports `notes_before: 0`, so the evidence set was **already empty
when the constraint was applied** — the constraint did not filter 63 notes
down to 0, it filtered an empty set. The loop in arm B made three `find_names`
calls, none of which return passages, then stopped at turn 3 of a 14-turn
budget and assembled nothing. Arm A, same brief, same corpus, same pinned
fork, walked the full budget and assembled 63.

So the answer reaches the loop and changes what it does — but through the
planning prose, not through the filter, and what it does is stop. Root cause
is not established here; it needs a fixture reproduction, not another paid
run.

## Second finding, separate from #649

Synthesis wrote **5 claims from an empty evidence set**, every one with zero
grounds. `confidence` is honestly `not_measured` and `evidence` honestly
reports `0/0`, so the record does not lie about it — but claims with no
grounds at all should probably not be written. Pre-existing: nothing in #649
touches the synthesis stage's behaviour on an empty set.

## Part 2, the live bar — PASSED (round 4)

`data/logs/2026-08-04-intake-fork-649/live/`. Branch `fix/649-fork-evidence-collapse`
@ `fe83708` (PR #660), run from `D:/axial` with the branch on `PYTHONPATH` —
no worktree junctions, live `data/` and `config/` in place.

**Does the analyst's answer change the evidence set?** Yes.

| | round 3 (before the fix) | round 4 (after) |
|---|---|---|
| retrieval turns | halted at 3 of 14 | ran all 14 |
| notes assembled | 0 | 34 |
| claims | 5, none grounded | 17, all 17 grounded |
| `intake_fork.effect` | run zeroed | 150 → 34 notes, 7 → 7 sources |
| Vignal, capped to 10 | — | 8 |
| confidence | — | medium |

The fork was `Assad regime` / `temporal_consequence`; the analyst picked
"Cap Vignal to limit its dominance" (`per_source_cap: 10`). Sources stayed at
7 because a cap trims within sources rather than dropping any, which is the
shape a cap should have. The two unconstrained baselines on this brief
assembled 63 and 106, so the constrained 34 is a real difference, not noise.

Caveat: the record persists counts, not assembled ids, so Vignal's 8 is its
share of *cited* evidence. The 150 → 34 figure is computed inside the run
against its own assembled set and is the attributable one.

### What actually cost money, and what fixed it

Rounds 1–3 lost three runs to the environment killing the process, and each
kill re-paid for the fork-check. None of that was the product. The run harness
was rebuilt around three rules, and round 4 succeeded first try:

1. **The journal is a file, not stdout.** Every event appends to `run.jsonl`
   and is fsynced before the next line executes. A killed run leaves a full
   record up to the kill.
2. **The fork is checkpointed.** `state.json` holds the accepted fork; any
   later start reuses it and buys nothing. Round 4 reused round 3's fork, so
   the whole run cost one analysis and zero fork-checks.
3. **Detached, not a child of the tool shell.** `Start-Process` with redirected
   output. A tool timeout can no longer kill the run.

A stubbed smoke pass over the harness (no model calls, free) caught two of its
own bugs before the paid run — a logger kwarg collision and a chunk-id parse
that would have thrown away an outcome already paid for. Both would have cost
a live run under the old process.
