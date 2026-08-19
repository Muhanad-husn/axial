# Slice 01: The window never cuts the first rotation

- **Feature:** 802-primary-outside-the-window
- **Slice slug:** the-window-never-cuts-the-first-rotation
- **Branch:** feat/802-primary-outside-the-window/01-the-window-never-cuts-the-first-rotation
- **Project directory:** .
- **Status:** planned
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

A name query returns at least one note from **every** source on the page. Where
the page draws on more sources than the limit, the limit is raised to cover
them rather than the alphabetically-last books being dropped.

## The defect, measured

`data/logs/2026-08-19-802-tilly-retrieval/summary.md`.

`find_notes` spreads members by source and truncates at `limit` (default 10),
visiting source groups in `source_id` **ascending** order. The `Charles Tilly`
page draws on 20 sources; `tilly-1978-f908c910464c` is 16th alphabetically:

```
limit= 10  total= 133  returned= 10  tilly-1978 present: False
limit= 15  total= 133  returned= 15  tilly-1978 present: False
limit= 16  total= 133  returned= 16  tilly-1978 present: True
```

Across all 19 analysis records, `tilly-1978` appears in `source_usage.sources`
**zero times** — including the four whose `coverage_map` names Charles Tilly.
The drafter never had a Tilly passage to select. Every source sorting in the
alphabetical first ten is cut on **0.0%** of pages; late-sorting ones on up to
9.8%.

`_round_robin_by_source` (#562) is a partial fix. It corrects the ordering
*within* a window; it does not correct *selection* when the source count
exceeds the limit, and there the rotation degenerates to "one note from each of
the alphabetically first `limit` sources" — the same alphabetical cut, one rung
up.

## The rule

**A rotation one member per source is only a spread across books while the
window is wide enough to hold the first full rotation.** So the limit is raised
to the distinct source count when it is smaller. Nothing is re-ordered, nothing
is ranked, and no source is promoted for what it is.

## Why not the alternatives

- **Raising `DEFAULT_LIMIT`.** A hand-tuned constant, a named tripwire, and it
  fixes nothing on a page with more sources than the new number.
- **Ranking the sources.** Explicitly out — "don't fix by ranking" binds, and
  size-ranking was measured to drift to hubs.
- **Rotating the group start offset per call.** Non-deterministic across calls
  over one pinned vault, which the query layer's determinism rule forbids.

## What it costs

Bounded by the corpus, because a page cannot draw on more sources than exist:

| | |
|---|---|
| Pages affected | 257 of 42,026 (0.6%) — **21.7% of the 1,182 in the 5+ source band** |
| Distinct sources on them | min 11, median 14, **max 35** |
| Mean window growth, affected pages | **1.62x** |
| Growth on the other 41,769 pages | none |

At 100+ sources this needs re-asking; it is stated in the docstring, not capped
with a number nobody chose.

## INVEST check

- **Independent:** one rule at three truncation sites; nothing depends on it.
- **Valuable:** the paper's central foil becomes reachable at all.
- **Small:** one helper, three call sites.
- **Testable:** free, offline, against the real vault.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a name page drawing on more sources than the default limit
When  a retrieval tool queries that name at the default limit
Then  every source on the page contributes at least one note
And   a page drawing on fewer sources than the limit is unchanged, note for note
And   the returned order is unchanged for any window that already covered every source
```

- **Boundary / endpoint:** the query API — `find_notes` and `get_name`, the
  tools the retrieval loop actually calls.
- **e2e test type:** API/integration test, over a fixture vault.
- **e2e test file (planned):** `tests/analysis/test_window_covers_every_source.py`

## Real-corpus validation (a norm, not a hook)

A green suite is not evidence here — #222 and #268. Two checks, both free:

- `find_notes("Charles Tilly")` at the **default** limit returns a
  `tilly-1978-f908c910464c` note, and it is a substantive one.
- Across all 257 over-limit pages, every source contributes, and the other
  41,769 pages return byte-identical results to `main`.

Then one paid check, because the issue's own bar is a bibliography and no
offline probe reaches it: re-run the analysis behind
`data/papers/a1039fad4da31320.md` and record whether `tilly-1978` reaches
`source_usage.sources`, the evidence set, and the paper's bibliography.

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-the-window-never-cuts-the-first-rotation
edits: src/axial/query/names.py
edits: src/axial/query/relations.py
creates: tests/analysis/test_window_covers_every_source.py
```

## Inner loop — initial unit test list

- [ ] `source_covering_limit` returns `limit` unchanged when it already covers every source.
- [ ] It returns the distinct source count when that exceeds `limit`.
- [ ] A member with no `source_id` counts as one source, matching the rotation's own `""` grouping.
- [ ] `find_notes` at the default limit returns one note from every source on an over-limit page.
- [ ] `find_notes` on an under-limit page returns exactly what it returns today.
- [ ] `get_name` (store-backed path) covers every source on an over-limit page.
- [ ] `get_name` (page-backed path, no store) does the same.
- [ ] `total` — the true pre-cap count — is unchanged in every case.

## Out of scope for this slice (deferred)

- An explicit maximum window. Bounded by the corpus at 35 today; a cap now is a
  number nobody chose.
- `where_names_meet`, `name_neighbors`, `who_cites` and the edge queries, whose
  truncations are over names and edges rather than over a per-source rotation.
- Anything that reaches a primary through its subject names rather than its
  author's name. Real, and not this.

## Definition of done

- [ ] Acceptance test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` and `uv run ruff check` green.
- [ ] Validated against the real corpus per the section above, offline and paid.
- [ ] Evidence collected and PR opened into `main` (`safe-pr`).

## Status / progress log

- 2026-08-19 planned, off the measurement in `data/logs/2026-08-19-802-tilly-retrieval/`.
