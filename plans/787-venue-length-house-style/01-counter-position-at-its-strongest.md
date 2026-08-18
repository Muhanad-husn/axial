# Slice 01: The counter-position is drafted at its strongest

- **Feature:** 787-venue-length-house-style
- **Slice slug:** counter-position-at-its-strongest
- **Branch:** feat/787-venue-length-house-style/01-counter-position-at-its-strongest
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

The drafting pass is told what a `counter-position` section is for, so it
states the opposing position at full strength before the paper answers it,
instead of introducing it already diminished.

## Why this is the defect it is

`data/papers/ca17d6077c1a7f5e.json` — the first real question-thesis paper the
system produced end to end (`data/logs/2026-08-18-784-cost-per-ask/`) — came
back `shape: weak` with one defect: the counter-position *"appears here as a
background condition rather than the post-2011 decision-maker, limiting its
explanatory force"*. That is Charter Principle IV failing at drafting scale,
and it is the same strawman shape already on record for the argument map.

The cause is visible in the prompts and is narrower than "the model was
careless":

- `compose_plan_prompt` (`src/axial/paper/plan.py:171`) **does** carry the
  instruction — *"At least one section must have role 'counter-position' and
  state the opposing position at its strongest"*.
- `compose_draft_prompt` (`src/axial/paper/draft.py:321`) **never mentions the
  counter-position at all.** The section's role reaches the drafter only as a
  bare interpolated string — `its role in the argument is "counter-position"` —
  with nothing anywhere in the prompt saying what that role obliges.

So the planner is told to steelman and the writer is not. This slice closes
that gap.

## INVEST check

- **Independent:** touches only `src/axial/paper/draft.py` and its tests.
  Shares no file with slice 03, so the two may be built in parallel.
- **Valuable:** the counter-position is the difference between a paper that
  adjudicates and one that dismisses. It is the founder-visible defect in the
  first real paper.
- **Small:** one prompt seam, one role, one added instruction block.
- **Testable:** unit tests pin the prompt's shape; the acceptance run measures
  the steelman verdict and `shape.band` across a sample.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a paper brief whose planned arc contains a section with role "counter-position"
When  an operator runs `uv run axial paper draft config/paper_briefs/dev/hollow-or-durable.yaml`
Then  the prompt sent for that section instructs the drafter to state the opposing position at its strongest before the paper answers it
And   the prompt sent for every other section carries no such instruction
And   the persisted record under data/papers/ still validates unchanged in every other respect
```

- **Boundary / endpoint:** CLI — `uv run axial paper draft <paper_brief_file>`
- **e2e test type:** API/integration test (a CLI run against a recorded client,
  asserting the composed prompt and the persisted record)
- **e2e test file (planned):** `tests/paper/test_counter_position_drafting.py`

## The measurement that closes the slice

A green suite is not the evidence here — this is a corpus-facing prompt change
and it is validated against real papers before it is called done.

**Design.** Five dev paper briefs from `config/paper_briefs/dev/`, three draws
each, both arms — 30 drafts at $0.008–$0.019 each, so roughly $0.40 plus judge
calls. Three draws because #695 and #700 both established that one draw of a
judged metric is not a measurement.

**Instruments, in priority order.**

1. **The steelman verdict** from `src/axial/validators/counter_position.py` —
   a bounded model call with a closed `steelman`/`strawman` vocabulary, built
   for Phase B and directly on target. Phase C's own gate deliberately takes
   the mechanical half only (PHASE-C.md §7.16 / line 727) and skips this call,
   so it is available and unused here.
2. **`shape.band`** — the signal the founder's ruling names. Coarser, whole-
   paper, one cheap call, already persisted per paper.

**The bar.** The strawman rate across the sample falls, and `shape.band` does
not regress on any brief. A prompt change that moves neither did nothing and
should not ship.

**Before the first arm runs:** copy the `data/papers/*.json` records being
measured into the run log. A re-draft overwrites the record it is measured
against.

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-counter-position-at-its-strongest
edits: src/axial/paper/draft.py
creates: tests/paper/test_counter_position_drafting.py
creates: tests/paper/test_draft_counter_position.py
```

## Inner loop — initial unit test list

- [ ] `compose_draft_prompt` for a section with role `counter-position` contains the steelman instruction.
- [ ] `compose_draft_prompt` for a section with role `claim`, `evidence`, `setup` or `synthesis` does not contain it.
- [ ] The instruction names the obligation concretely — state the opposing position at its strongest, in its own best terms, before the paper responds — rather than repeating the role name back.
- [ ] The steelman instruction does not weaken the existing voice contract: a section's `a`/`b`/`c` claim-kind rules and the marker grammar are unchanged in the composed prompt.
- [ ] A drafted counter-position section still parses through `parse_draft_response` with its markers and `new_claims` intact.

## Out of scope for this slice (deferred)

- Any length target or word budget (slice 02).
- Changing `compose_plan_prompt`, which already carries the instruction.
- Making the shape check or the counter-position gate blocking. Both are
  advisory by design and stay that way.
- Adding a new defect kind. `strawman_counter_position` already exists in the
  closed vocabulary (PHASE-C.md §7.16).

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green locally.
- [ ] Refactor pass complete with the bar green.
- [ ] **Real-corpus measurement run complete**, logged under `data/logs/<date>-787-counter-position-steelman/`, with the before-records copied in first.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-18 planned.
