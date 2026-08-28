# Slice 03: Two notes meet at a shared group

- **Feature:** derived-vocabulary
- **Issue:** [#807](https://github.com/Muhanad-husn/axial/issues/807)
- **Slice slug:** two-notes-meet-at-a-shared-group
- **Branch:** feat/derived-vocabulary/03-two-notes-meet-at-a-shared-group
- **Project directory:** .
- **Status:** ☑ done — PR #821
- **Walking skeleton?** no

> **Corrected 2026-08-28, before building.** The previous version of this plan
> made the derived join a **tool offered to the model**, with a `ToolSpec`, an
> edit to `src/axial/retrieve/dispatcher.py`, and an acceptance criterion
> reading "the trajectory records at least one call to the derived-join tool".
> That cannot work on the arm it targets. `run_map_ask_for_brief` is fully
> deterministic after `decompose_brief` — land, corridor, assemble — with no
> tool loop at all, and `axial.answer.record` writes an honest empty trajectory
> for it, recording what the map did in a `map_retrieval` block instead. A
> trajectory entry is not the observable on this arm, and there is no loop to
> offer a tool to. The join is a **deterministic step in the map walk**. See
> "The join is a step, not a tool" below.

## Goal — the minimum testable behaviour

A brief can be run through a retrieval arm that reaches passages by what they
share in meaning: `axial brief run <brief> --arm map+vocab`. Two passages meet at
a shared mechanism the way they meet at a shared name today, and the run's own
record shows which categories did it.

The column is a parameter, so this works on whatever slice 02 has assigned.
Slice 02 assigned `mechanism` first and the other six cleared columns only if
slice 05 says the join pays, so `mechanism` is what this slice is exercised on.

## Why this slice exists

This is the slice the whole feature is for, and it is the slice that makes the
feature measurable. Everything before it produces an artifact. Without a
retrieval arm carrying the derived join, slice 05 would compare two layers that
both exist today and its number could not be attributed to anything built here.

An earlier draft added the tool to the surface and deliberately left it unwired.
Review and independent verification both found the same consequence: the
decision would have come out the same if slices 01 to 03 were never built.
Wiring it is what closes that.

## The join is a step, not a tool

The map arm has no tool loop. `run_map_ask_for_brief` runs one model call, the
door (`decompose_brief`), and everything after it is deterministic:

```
door -> landing -> corridor -> assembly
```

`map+vocab` adds one deterministic step in that walk:

```
door -> landing -> corridor -> vocabulary neighbours -> assembly
```

Where the corridor pulls in positions that **argue with** what landed, the
vocabulary step pulls in positions that **share a category** with what landed.
Both are deterministic, both feed the same `assemble_map_evidence`.

**The precedent is already in the file.** `MatchedPosition` and `positions_on`
(#650) are a position type reached by a table lookup — nothing encoded, nothing
scored, no model call, joining `positions.chunk_ids` against `note_names`. This
step is that shape with the vocabulary assignment in place of the name table,
and `assemble_map_evidence` already takes a union of position types, so a fourth
member fits its signature without widening anything.

Three things follow, and all three are improvements on the tool version:

- **A deterministic step cannot be declined.** The recorded finding that four of
  eight query tools returned zero stops being a risk here, because no model
  chooses whether to take this edge.
- **The acceptance criterion is checkable without a model in the loop.** Only the
  door makes a call; the join is a table join.
- **The arm plumbing already exists.** #808 shipped `arm` as a pass-through
  rather than an enum, and says so in its own module docstring: a slice adding a
  real third arm does it by teaching a lower layer what that string means. This
  slice is that lower layer.

**Observability goes in `map_retrieval`, never in the trajectory.**
`_map_retrieval_to_dict` in `src/axial/answer/record.py` is the map arm's audit
trail and already carries `asks`, `landed`, `corridor` and the assembled ids. The
join adds a `vocabulary` block beside them: the categories reached, how many
notes each contributed, and how many distinct sources those notes came from.
Writing a fabricated trajectory entry to keep a downstream reader fed is exactly
what that function's docstring refuses to do, and this slice does not start.

**Cap what the step pulls in.** A `mechanism` category holds roughly 295 notes
against a corridor bounded by relation count. Uncapped, one category would swamp
the landed positions in assembly. `assemble_map_evidence`'s round-robin protects
the *order* but not the total, so the step takes a per-category cap, prefers
sources other than the landed position's, and records the cap it applied. A cap
that bit is a fact about the run and belongs in the record.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a persisted derived vocabulary in which a mechanism category holds notes
       from three different sources, and a brief whose landed positions carry
       notes in that category
When   an operator runs `uv run axial brief run <brief> --arm map+vocab`
Then   the run completes and persists an analysis record
And    the record's `map_retrieval` carries a `vocabulary` block naming the
       categories reached, the notes each contributed, and the distinct sources
       those notes came from
And    the assembled evidence contains at least one chunk that reached it only
       through the category edge, so the answer rests partly on passages that
       met at a shared mechanism rather than a shared name
And    the same brief run with `--arm map` assembles without that step and
       records no `vocabulary` block
And    neither arm's trajectory is written to; both stay the honest empty list
       the map path already produces
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
edits: src/axial/argmap/ask.py
edits: src/axial/argmap/test_ask.py
edits: src/axial/answer/record.py
edits: src/axial/answer/test_record.py
creates: src/axial/argmap/vocabulary_join.py
creates: src/axial/argmap/test_vocabulary_join.py
depends-on: 02-a-derived-vocabulary-is-persisted
```

`src/axial/retrieve/tools.py` and `src/axial/retrieve/dispatcher.py` are **not**
edited. They are the name-layer loop's tool surface, and this arm has no loop.

## Inner loop — initial unit test list

- [ ] Given a landed position and a column, the step returns the other positions
      whose notes share a category with it, each carrying the category, the
      contributing chunk ids, and its own sources.
- [ ] A position already landed, or already in the corridor, is not returned
      again — the same guard `build_corridor` already applies.
- [ ] A note whose value the scheme refused contributes no edge, and the reason
      is distinguishable from a category holding exactly one member, from "no
      such note", and from "no such column".
- [ ] Neighbours are ordered so that sources other than the landed position's
      come first.
- [ ] The per-category cap is applied, and the record says it was applied and at
      what value.
- [ ] Asking for a column with no persisted vocabulary fails naming the column,
      not with a stack trace and not with an empty success.
- [ ] The step runs on the `map+vocab` arm and not on `map`; the `name` arm is
      untouched.
- [ ] An unknown `--arm` value is refused, naming the arms that exist.
- [ ] The trajectory stays empty on both map arms.

## Design notes for the executor

- **One step, not twelve.** The column is a parameter. A separate code path per
  column would be twelve near-identical joins over one table.
- **The level is a parameter too.** The founder's 2026-08-28 ruling makes the
  vocabulary a tree; slice 02 shipped depth 1 with a shape that admits depth 2.
  The step takes the level, or resolves to the finest level the column has, so a
  second level becomes reachable without a second code path.
- **`--arm` is a pass-through, not an enum each caller re-declares.** #808 already
  established this and `brief sweep --arm` already accepts `map+vocab`. This
  slice teaches the lower layer what the string means; it does not add a second
  arm registry.
- **Read `positions_on` and `MatchedPosition` first** (`src/axial/argmap/ask.py`,
  #650). They establish the return shape for a position reached by a table
  lookup rather than a score, which is exactly what this is.
- **Cross-book neighbours come first.** Only 40.5% of argument-map edges reach
  another book (#651). Ordering, the per-category cap, and the source count in
  the record are what let a reader see a category is one book talking to itself.

## Out of scope for this slice (deferred)

- Changing the `name` or `map` arms, the step budget, or the assembly cap on
  either.
- Any change to `src/axial/retrieve/`. The name-layer tool surface is not touched.
- Building any page or vault artifact from a category.
- Cross-column joins: notes sharing both a mechanism and an assumption.
- Building depth 2 of the vocabulary. Slice 02's own out-of-scope note holds.
- Removing or demoting any name-keyed tool.

## Definition of done

- [x] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [x] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [x] Refactor pass complete with the bar green.
- [x] `uv run ruff check` clean.
- [x] Slice's tests run in CI (`tdd-ci`).
- [x] **Exercised against the real vocabulary** built in slice 02, on at least
      three `mechanism` categories, with the members **read by a human** to
      confirm they are actually saying the same thing. A model agreeing with the
      scheme it was handed is not evidence that a category means anything, and
      slice 01 measured that agreement at 61.4% on this column. One real brief
      run on the `map+vocab` arm, with the persisted `map_retrieval` block
      inspected. Log to `data/logs/<YYYY-MM-DD>-vocabulary-join/`.
      **[x] DONE.** Both brief runs, the `map_retrieval` inspection and the
      log are complete (`data/logs/2026-08-28-vocabulary-join/`). The human
      read of three `mechanism` categories -- one large, one mid, one small,
      six members each, one per distinct source -- was **approved by the
      founder on 2026-08-28**, with the known mis-file on the record at the
      time of approval: `chouliaraki-2024` under `war-and-state-formation` for
      a passage about the First World War replacing a horse-drawn streetcar.
      The approval is that the categories are good enough to join on, not that
      every assignment is right. The sheet and the verdict are at
      `category-reading.md` (gitignored -- the members carry source-derived
      answer text).
- [x] Evidence collected and PR opened into the default branch (`safe-pr`).

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
- 2026-08-28 corrected before building, after the executing session read the map
  arm's code: the arm is deterministic after the door and has no tool loop, so a
  `ToolSpec`, a `dispatcher.py` edit and a trajectory assertion were all wrong.
  The join is a deterministic step between the corridor and assembly, its
  observable is the record's `map_retrieval` block, and `src/axial/retrieve/` is
  no longer touched at all.
- 2026-08-28 built and exercised on the real corpus. One brief run on
  `--arm map+vocab` ($0.081, 240s): 12 `mechanism` categories reached, and
  **38 of the 90 assembled chunks (42.2%) reached assembly only through the
  category edge**, spanning 16 distinct sources. Every category hit the
  per-category cap of 20. Log: `data/logs/2026-08-28-vocabulary-join/`.
  PR [#821](https://github.com/Muhanad-husn/axial/pull/821).
- 2026-08-28 one fix outside the declared file list: `brief sweep` collapsed
  its `arm` into `run_brief`'s `use_map` boolean, so `--arm map+vocab` ran the
  NAME layer while recording the arm as `map+vocab`. #809 reads the arms off
  exactly those directories. The arm is now passed through verbatim.
- 2026-08-28 the first live run exposed the defect the acceptance criterion
  could not see: all 38 category-edge notes assembled at index 52 or later and
  **the answer cited none of them**, because `assemble_map_evidence` walks
  positions in the order given under a shared cap of 90 and the step was
  appended last. Fixed by assembling the vocabulary before the corridor
  (DEC-73), judging cross-source per category rather than against the union of
  every landed source, and recording offered and assembled counts separately.
  Re-run: category-edge chunks 38 → 63, cited via the edge 0 of 20 → 2 of 9.
- 2026-08-28 five deferred loose ends filed as [#822](https://github.com/Muhanad-husn/axial/issues/822).
- 2026-08-28 founder approved the category read. Slice 03 complete; every
  definition-of-done item met.
