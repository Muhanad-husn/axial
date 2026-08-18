# #787 slice 01 — does the counter-position prompt change move the shape check?

**Answer: it cannot be told from this instrument, on this sample.** Both arms
returned `strong` on every draft with zero defects. The measurement is a null,
and the null is about the instrument, not about the change.

## Command and arms

Driver: `run_787_arm.py <arm> <draws>` (deleted with the branch — it drives one
measurement and is not a permanent script). Nine dev paper briefs, two draws
each, two arms, run in `D:/axial` because `data/` does not exist in a worktree.

| Arm | Branch | HEAD | Prompt change |
|---|---|---|---|
| `before` | `main` | `7f18223` | absent |
| `after` | `feat/787-venue-length-house-style/01-counter-position-at-its-strongest` | `fb9bdfb` | present |

The existing nine `data/papers/*.json` records were copied to `before-records/`
before the first draw, because `axial paper draft` overwrites
`data/papers/<paper_brief_id>.json` and each draw would otherwise destroy the
last. Every draw's own record is kept under `<arm>-records/`.

## Result

| Arm | n | bands | counter-position section planned | counter-position flagged | any defect |
|---|---|---|---|---|---|
| before | 17 | `strong` ×17 | 17/17 | **0** | **0** |
| after | 18 | `strong` ×18 | 18/18 | **0** | **0** |

35 successful drafts, 79 minutes wall clock, `$0.068` in shape-check calls plus
the drafting spend.

## What this does and does not establish

**It does not validate the change.** No movement was measured, so nothing about
the prompt edit is confirmed by this run.

**It does establish that `shape.band` cannot serve as the acceptance signal for
prompt work on these briefs.** The check returned `strong` on 35 of 35 drafts
across both arms. A metric that never varies cannot report an improvement or a
regression, and the founder's ruling had nominated exactly this signal. That
nomination is now measured and refuted for this purpose. Recording it is the
main thing this run bought.

**The two samples are not the same distribution.** The defect that started this
work is in `data/papers/ca17d6077c1a7f5e.json`, drafted end to end by
`axial ask` from a real analyst question
(`data/logs/2026-08-18-784-cost-per-ask/`). It came back `shape: weak` with a
named counter-position defect. The nine dev briefs here are curated, each
carrying a hand-written thesis, and every one of them plans a counter-position
section and passes. Whatever produces a strawman is not present in them.

## The failure worth keeping

One draw of 36 failed, on the **before** arm, and it is a pre-existing drafting
failure mode rather than anything this change touches:

```
before/what-later-accounts-did-to-quasi-states/draw1
error: citation marker [pc010] in section 's6' (sentence 0) names no claim in
the record; every marker must resolve to a paper_claim_id (§7.5)
```

The drafter emitted `[pc010]` where the grammar is `[pc-010]`, and the run
correctly refused rather than persisting an unresolvable citation. One in 35
drafts, on `openai/gpt-5.6-luna`. Not filed as an issue here; noted because a
sweep of this size is where a 3% failure rate becomes visible at all.

## What should happen next

1. **Slice 01 ships on reasoning, with this null recorded, not hidden.** The gap
   it closes is objective and does not need a judged metric to see:
   `compose_plan_prompt` instructs the planner to state the opposing position at
   its strongest and `compose_draft_prompt` never mentioned the counter-position
   at all. The change adds one instruction to one role, cannot regress any other
   role's prompt, and the full suite is unchanged at 2,508.
2. **Slice 02's acceptance bar needs rewriting before it is built.** Its plan
   currently reuses `shape.band` for the same purpose, and this run says that
   bar is unmeasurable on these briefs.
3. **The sharper instrument, if one is wanted**, is the bounded
   steelman/strawman judge already in
   `src/axial/validators/counter_position.py` — a binary verdict on the
   counter-position section itself rather than a three-value band over the whole
   paper. Phase C's own gate deliberately skips it (PHASE-C.md §7.16), so it is
   built, tested and unused.
4. **A real measurement needs the input that produced the defect** — asks from
   real questions, not curated dev briefs. That is a more expensive run and it
   should be scoped deliberately rather than bolted onto this slice.
