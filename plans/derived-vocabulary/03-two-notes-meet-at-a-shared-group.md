# Slice 03: Two notes meet at a shared group

- **Feature:** derived-vocabulary
- **Issue:** [#807](https://github.com/Muhanad-husn/axial/issues/807)
- **Slice slug:** two-notes-meet-at-a-shared-group
- **Branch:** feat/derived-vocabulary/03-two-notes-meet-at-a-shared-group
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Retrieval can ask, of a note, which other notes share its mechanism — or its
concession, or its assumption — and get them back across sources. This is the
job a name page does today, done on meaning instead of on a shared string.

## Why this slice exists

This is the slice the whole feature is for. Everything before it produces an
artifact; this is where the artifact becomes a way for two passages to meet.
Without it, the derived vocabulary is a report and the retrieval loop still has
only names to walk.

## INVEST check

- **Independent:** adds one tool to the existing tool surface. Nothing already
  in the loop changes behaviour; the tool is available and unused until a brief
  reaches for it.
- **Valuable:** an analyst — or the retrieval loop acting for one — can follow
  a mechanism across books for the first time. It is observable on its own,
  before any comparison run.
- **Small:** one query function, one `ToolSpec`. The store it reads is slice
  02's artifact.
- **Testable:** the tool has a defined return shape and a real CLI-reachable
  boundary through the retrieval loop, exercised the way the existing tools are
  in `src/axial/retrieve/test_tools.py`.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given  a persisted derived vocabulary in which a mechanism group holds notes
       from three different sources
When   the retrieval loop calls the tool for that group's column and one of its
       member notes
Then   it returns the group's other member notes with their source ids, their
       answer sentences, and the count of distinct sources the group spans
And    the group's label is returned alongside, so the caller can say what the
       shared thing is
And    a note whose answer grouped with nothing returns an empty result that
       says so, rather than an error or a silent fallback to a name lookup
```

- **Boundary / endpoint:** the retrieval tool surface in
  `src/axial/retrieve/tools.py`, reachable through the loop the same way
  `where_names_meet` and `positions_on` are
- **e2e test type:** integration test through the tool dispatcher, not the
  query function directly
- **e2e test file (planned):** `src/axial/retrieve/test_tools.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 03-two-notes-meet-at-a-shared-group
edits: src/axial/retrieve/tools.py
edits: src/axial/retrieve/test_tools.py
creates: src/axial/query/vocabulary.py
creates: src/axial/query/test_vocabulary.py
depends-on: 02-a-derived-vocabulary-is-persisted
```

## Inner loop — initial unit test list

- [ ] Given a note and a column, the query returns the other members of that
      note's group, each with source id and answer sentence.
- [ ] The result carries the group's label and the count of distinct sources
      the group spans — the reader needs to know a group is one book talking to
      itself.
- [ ] A note that grouped alone returns an empty member list and a stated
      reason, distinct from "no such note" and from "no such column".
- [ ] Members are ordered so that sources other than the asking note's come
      first — a cross-book neighbour is worth more than a same-book one, and
      the recorded finding is that only 40.5% of argument-map edges reach
      another book.
- [ ] Asking for a column that has no persisted vocabulary fails with a message
      naming the column, not with a stack trace or an empty success.
- [ ] The tool is declared in the provider tool list with a description that
      says what a group is, so the model calling it knows it is asking about a
      shared mechanism rather than a shared word.

## Design notes for the executor

- **One tool, not twelve.** The column is a parameter. A separate tool per
  column would be twelve near-identical specs in the prompt and would push the
  tool surface past what a model reliably chooses between — the recorded
  finding is that four of eight query tools already returned zero.
- **Do not wire it into the default loop in this slice.** Adding it to the
  surface is enough to test and to measure. Whether the loop prefers it over a
  name lookup is a question slice 05's numbers answer, not one this slice
  presumes.
- **Read the existing tools first.** `_where_names_meet`, `_positions_on` and
  `_find_notes` in `src/axial/retrieve/tools.py` establish the return shape,
  the detail-string helpers, and how a result reports its own span. Match them.
- **A repeat means nowhere else to go.** The recorded finding is that 91% of
  re-asks hit a `total == count` result. Return the totals the caller needs to
  know it has exhausted a group, rather than letting it discover that by
  asking twice.

## Out of scope for this slice (deferred)

- Changing which tool the retrieval loop reaches for first, or its step budget.
- Building any page or vault artifact from a group.
- Cross-column joins — notes that share both a mechanism and an assumption.
- Removing or demoting any name-keyed tool.

## Definition of done

- [ ] Acceptance/e2e test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; fast tier green locally, CI green for
      the rest.
- [ ] Refactor pass complete with the bar green.
- [ ] `uv run ruff check` clean.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] **Exercised against the real vocabulary** built in slice 02, on at least
      one group per cleared column, with the members read by a human to confirm
      they are actually saying the same thing. Log to
      `data/logs/<YYYY-MM-DD>-vocabulary-tool/`.
- [ ] Evidence collected and PR opened into the default branch (`safe-pr`).

## Status / progress log

- 2026-08-27 planned.
