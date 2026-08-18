# Slice 02: Length is a target the plan allocates to

- **Feature:** 787-venue-length-house-style
- **Slice slug:** length-is-a-plan-target
- **Branch:** feat/787-venue-length-house-style/02-length-is-a-plan-target
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A paper brief may declare a target word count, and the arc planner allocates a
share of it to each section it plans. Nothing is truncated after drafting.

## Why a target and not a cap

Journals disagree about length by a factor of four — IJMES caps an article at
10,000 words including endnotes, Nature's guidance runs 2,500–4,300 — which is
what confirms length is an input the analyst sets rather than a constant
derived from anywhere. And the founder's ruling is explicit that this ships
*after* slice 01 and not before it: a tight cap crushes the counter-position
section first, which is exactly how a strawman gets written.

Post-hoc truncation is the failure mode this slice exists to avoid. A paper cut
to length after drafting loses its last section, which is usually the synthesis
— the part that was the paper's own contribution.

## INVEST check

- **Independent:** depends on slice 01 (shared file, and the sequencing above),
  but nothing depends on it except slice 05.
- **Valuable:** an analyst gets an essay sized for what they will do with it,
  and the drafter stops writing to no budget at all.
- **Small:** one optional brief field, one number threaded into two prompts.
- **Testable:** the allocation is observable in the persisted plan; the
  measurement checks the drafted result lands near the target.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a paper brief that declares target_words: 3000
When  an operator runs `uv run axial paper draft <that brief>`
Then  the persisted plan assigns each section its own share of the 3000-word target
And   the drafting prompt for each section states that section's own word budget
And   the rendered paper's word count lands within a stated tolerance of 3000 without any text having been cut after drafting
And   a brief that declares no target_words drafts exactly as it does today
```

- **Boundary / endpoint:** CLI — `uv run axial paper draft <paper_brief_file>`
- **e2e test type:** API/integration test
- **e2e test file (planned):** `tests/paper/test_length_target.py`

## The hazard this slice creates, and the decision already taken

`compute_paper_brief_id` (`src/axial/paper/brief.py:155`) hashes an explicit
four-key dict — `thesis`, `analysis_ids`, `lens`, `title`. Adding `target_words`
to that dict changes **every existing brief's id** and orphans all 8 records in
`data/papers/`.

**Decision: include it in the hash.** A different target length genuinely is a
different paper, and a content-keyed id that ignores a field which changes the
output is the bug, not the re-key. The cost is one re-draft per brief at
$0.008–$0.019, which is cheap and buyable. Do not work around this by excluding
the field from the hash.

A brief that declares no `target_words` must hash to **exactly its current id** —
so the field's absence has to be represented in the canonical dict the same way
it is today, not as a new key with a null value that shifts every hash. Pin this
with a test against a known existing id before touching anything else.

## Files (parallel-safety declaration)

```aeo-independence
slice: 02-length-is-a-plan-target
edits: src/axial/paper/brief.py
edits: src/axial/paper/plan.py
edits: src/axial/paper/draft.py
edits: src/axial/paper/record.py
creates: tests/paper/test_length_target.py
creates: tests/paper/test_plan_length_allocation.py
depends-on: 01-counter-position-at-its-strongest
```

## Inner loop — initial unit test list

- [ ] A brief with no `target_words` computes the same `paper_brief_id` it computes today (pinned against a known existing id).
- [ ] A brief declaring `target_words` computes a different id from the same brief without it.
- [ ] `target_words` is rejected when it is not a positive integer, with the same typed-error shape the other brief fields use.
- [ ] `compose_plan_prompt` states the total target and asks the planner to allocate a per-section share.
- [ ] The parsed `Plan` carries each section's allocated word budget, and the allocations sum to the target.
- [ ] `compose_draft_prompt` states that one section's own budget; with no target set, the prompt is byte-identical to slice 01's.
- [ ] The counter-position section is never allocated the smallest share by construction — a floor, or the allocation is the planner's with the instruction that the counter-position is not the section to squeeze.

## The measurement that closes the slice

**Rewritten 2026-08-18, after slice 01's measurement refuted the bar this
section originally carried.** It previously asked for `shape.band` across five
dev briefs. That run happened
(`data/logs/2026-08-18-787-counter-position-steelman/`) and returned `strong`
on **35 of 35 drafts across both arms**. A metric that never varies cannot
report an improvement or a regression, so that bar was unmeasurable here.

The bar now splits in two, and only half of it needs a model at all.

**The primary claim has an oracle, so it is a test, not a judgement.** Does the
rendered paper land within a stated tolerance of `target_words`, and did any
text get cut after drafting? Both are countable. Assert them in the acceptance
test and no judge is involved.

**Only the regression check needs a model**, and it should not be
`shape.band`. Use the bounded steelman/strawman verdict in
`src/axial/validators/counter_position.py` -- a binary judgement on the
counter-position section itself, rather than a three-value band over the whole
paper. It discriminates where the band cannot. **A length target that
reintroduces the strawman has not shipped**, however close its word count
lands.

**Run it against real asks, not the dev briefs.** The same slice-01 run
established that the nine dev briefs are the wrong substrate for judging
writing quality: each carries a hand-written thesis, every one plans a clean
counter-position, and all of them pass. The defect that motivated this work
came from `axial ask` on a real analyst question. Reuse
`run_787_ask_arm.py`'s shape from slice 01 rather than the brief driver.

Log under `data/logs/<date>-787-length-target/`, with the paper records copied
in before the first arm.

## Out of scope for this slice (deferred)

- Any post-hoc truncation path. If the drafted paper misses the target, that is
  reported, never cut.
- A per-venue length. There are no venues.
- Exposing `target_words` through the web client or the ask path. The brief is
  the boundary for this slice.
- An abstract, which has its own word budget (slice 04).

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [ ] Refactor pass complete with the bar green.
- [ ] Real-corpus measurement run complete and logged, showing the length lands and slice 01's gain holds.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
