# #787 slice 01, second attempt — the real ask, not dev briefs

**The defect this slice exists to fix does not reproduce.** `main` drafts the
same question three times and returns `strong` every time, with no
counter-position defect. The single `weak` paper that motivated the work was a
draw, not a standing failure.

## Why this run happened

The first attempt (`../2026-08-18-787-counter-position-steelman/`) measured nine
curated dev paper briefs and returned `strong` on 35 of 35 drafts across both
arms — a null caused by the substrate. This run goes at the input that actually
produced the defect: the exact question and case from
`../2026-08-18-784-cost-per-ask/run.ps1`, asked through `axial ask`.

```
case     : Syria, 1920-2024 -- state formation and who the arrangement favoured
question : Did the mandate-era institutions or the Baath decide who held power
           in Syria after 2011?
```

## Result

| Arm | Branch | HEAD | n | bands | counter-position flagged |
|---|---|---|---|---|---|
| before | `main` | `7f18223` | 3 | `strong` ×3 | 0 |
| after | slice 01 | `8435d1e` | 2 | `strong` ×2 | 0 |

Five asks, roughly 14 minutes each, about `$0.04` a draw.

The original record, kept here as `original-defect-record.json`:

```
ca17d6077c1a7f5e   band: weak
  defect s2 (counter-position): "The counter-position is introduced already
  diminished — 'appears here as a background condition rather than the
  post-2011 decision-maker, limiting its explanatory force' — rather than being
  presented at its strongest before the paper's own response."
```

Same question, same corpus, same code as the `before` arm. One `weak` in four
drafts on `main`; three `strong` in the three fresh ones.

## What this establishes

**The prompt gap is real and is not in question.** `compose_plan_prompt`
instructs the planner to state the opposing position at its strongest;
`compose_draft_prompt` never mentioned the counter-position at all. That is a
fact about the code, readable without any measurement.

**The claimed impact of closing it is unestablished.** No difference was
measured, in either direction, on either substrate.

**The experiment was underpowered, and that was predictable before it ran.**
The defect's base rate on `main` looks like roughly 1 in 4. Detecting a change
in a 25% event with n=3 is not possible — the arms would look identical under
almost any true effect. At ~14 minutes and `$0.04` a draw, the sample needed to
resolve it is upwards of ten hours of wall clock. That arithmetic should have
been done before the first arm, not after the second.

**The shape check varies on identical input**, which is consistent with what is
already on record elsewhere in this system: Gather does not reproduce 36% of its
own disagreements, and merge disagrees with itself at 13.3%. A judged band is a
sample, not a reading. One `weak` is one draw.

## Recommendation

Ship slice 01 on the strength of the gap it closes, not on a measured
improvement, and record this null in the PR rather than omitting it. The change
adds one instruction to one role, cannot affect any other role's prompt, and
leaves the suite unchanged at 2,508. The alternative — ten hours of asks to
resolve a 25% base rate — is not a proportionate price for a twenty-line prompt
edit that is obviously correct in direction.

What should **not** happen is quoting this run as validation. It is not one.

## Operational notes

- Two earlier attempts at this arm were launched through the agent harness's
  background lane and were killed mid-run, once during after/draw3 and once
  during before/draw1. Nothing bought was lost: every completed draw is fsynced
  to `run.jsonl` and its record copied into `<arm>-records/` before the next
  draw starts. The third attempt used `Start-Process`, a genuinely detached
  Windows process, which is what this repo's own operating notes prescribe for
  long runs, and it survived.
- The after arm is n=2 rather than n=3 for that reason. Re-running it would have
  re-bought draws 1 and 2, since the journal appends.
- `run_787_ask_arm.py` captures each ask's output only on completion, so a draw
  in flight shows no progress at all. A watcher has to fall back to process CPU
  and the process tree. Worth fixing if this driver is ever reused.
