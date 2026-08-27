# Slice 03: Two notes meet at a shared group

- **Feature:** derived-vocabulary
- **Issue:** [#807](https://github.com/Muhanad-husn/axial/issues/807)
- **Slice slug:** two-notes-meet-at-a-shared-group
- **Branch:** feat/derived-vocabulary/03-two-notes-meet-at-a-shared-group
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A brief can be run through a retrieval arm that reaches passages by what they
share in meaning: `axial brief run <brief> --arm map+vocab`. Two passages meet
at a shared mechanism the way they meet at a shared name today, and the run's
own trajectory shows it happened.

The column is a parameter, so this works on whatever slice 02 has assigned.
Slice 02 assigns `mechanism` first and the other six cleared columns only if
slice 05 says the join pays, so `mechanism` is what this slice is exercised on.

## Why this slice exists

This is the slice the whole feature is for, and it is the slice that makes the
feature measurable. Everything before it produces an artifact. Without a
retrieval arm carrying the derived join, slice 05 would compare two layers that
both exist today and its number could not be attributed to anything built here.

An earlier draft of this plan added the tool to the surface and deliberately
left it unwired. Review and independent verification both found the same
consequence: the decision would have come out the same if slices 01 to 03 were
never built. Wiring it is what closes that.

## INVEST check

- **Independent:** depends on slice 02's artifact and on nothing else. Adds a
  new arm value beside the existing ones; the `name` and `map` arms are
  untouched, so nothing already in the pipeline changes behaviour.
- **Valuable:** an analyst can follow a mechanism across books for the first
  time, through a real command, before any comparison run.
- **Small:** one query module, one `ToolSpec`, one arm value threaded through
  the retrieval dispatcher. The store it reads is slice 02's artifact.
- **Testable:** observable at the CLI, in the answer and in the trajectory log
  the run already writes.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a persisted derived vocabulary in which a mechanism group holds notes
       from three different sources, and a brief those notes bear on
When   an operator runs `uv run axial brief run <brief> --arm map+vocab`
Then   the run completes and persists an analysis record
And    the retrieval trajectory records at least one call to the derived-join
       tool, with the group's label and the count of distinct sources it spans
And    evidence assembled through that call reaches the record, so the answer
       rests partly on passages that met at a shared mechanism rather than a
       shared name
And    the same brief run with `--arm map` produces a trajectory with no call
       to that tool
```

- **Boundary / endpoint:** CLI — `uv run axial brief run <brief> --arm map+vocab`
- **e2e test type:** CLI integration test driving the real command against a
  temporary data directory, with the model client stubbed
- **e2e test file (planned):** `src/axial/test_cli_ask.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 03-two-notes-meet-at-a-shared-group
edits: src/axial/cli.py
edits: src/axial/test_cli.py
edits: src/axial/test_cli_ask.py
edits: src/axial/retrieve/tools.py
edits: src/axial/retrieve/test_tools.py
edits: src/axial/retrieve/dispatcher.py
creates: src/axial/query/vocabulary.py
creates: src/axial/query/test_vocabulary.py
depends-on: 02-a-derived-vocabulary-is-persisted
```

## Inner loop — initial unit test list

- [ ] Given a note and a column, the query returns the other members of that
      note's group, each with source id and answer sentence.
- [ ] The result carries the group's label and the count of distinct sources
      the group spans.
- [ ] A note whose value the scheme refused returns no members and a stated
      reason, distinct from a category holding exactly one member, from "no
      such note", and from "no such column".
- [ ] Members are ordered so that sources other than the asking note's come
      first.
- [ ] Asking for a column with no persisted vocabulary fails with a message
      naming the column, not with a stack trace or an empty success.
- [ ] The tool is offered to the model only on the `map+vocab` arm; the `name`
      and `map` arms see the tool list they see today.
- [ ] An unknown `--arm` value is refused, naming the arms that exist.

## Design notes for the executor

- **One tool, not twelve.** The column is a parameter. Twelve near-identical
  specs would push the tool surface past what a model reliably chooses between,
  and the recorded finding is that four of eight query tools already returned
  zero.
- **`--arm` is a pass-through, not an enum each caller re-declares.** Slice 04
  puts the same selector on `brief sweep`. If the arm list lives in one place,
  a new arm becomes available everywhere at once and the two slices stay
  independent of each other. If it is re-declared per command, they do not.
- **Read the existing tools first.** `_where_names_meet`, `_positions_on` and
  `_find_notes` in `src/axial/retrieve/tools.py` establish the return shape,
  the detail-string helpers, and how a result reports its own span. Match them.
- **A repeat means nowhere else to go.** 91% of re-asks hit a `total == count`
  result. Return the totals a caller needs to know it has exhausted a group,
  rather than letting it discover that by asking twice.
- **Cross-book neighbours come first.** Only 40.5% of argument-map edges reach
  another book. Ordering, and the source-span count in the result, are what let
  a caller see a group is one book talking to itself.

## Out of scope for this slice (deferred)

- Changing the `name` or `map` arms, the step budget, or which tool the loop
  reaches for first on either of them.
- Building any page or vault artifact from a group.
- Cross-column joins: notes sharing both a mechanism and an assumption.
- Removing or demoting any name-keyed tool.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Exercised against the real vocabulary** built in slice 02, on at least
      three `mechanism` categories, with the members **read by a human** to
      confirm they are actually saying the same thing. A model agreeing with the
      scheme it was handed is not evidence that a category means anything, and
      slice 01 measured that agreement at 61.4% on this column. One real brief
      run on the `map+vocab` arm, with the trajectory inspected. Log to
      `data/logs/<YYYY-MM-DD>-vocabulary-tool/`.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Status / progress log

- 2026-08-27 planned.
- 2026-08-27 revised after review and independent verification, which
  independently agreed the derived vocabulary reached neither measured arm.
  Founder ruling the same day: three arms. The tool is now wired into a
  selectable retrieval arm, which also moves this slice's acceptance criterion
  from a Python module path to a real command.
- 2026-08-27 aligned to slice 01 as shipped: there is no clustering and no
  cosine threshold anywhere in this feature any more, so a group is a category a
  model assigned and a note without one is a refusal, not a singleton. Exercised
  on `mechanism`, which is the column slice 02 assigns first.
