# 2026-08-17 — #783 reader render, re-rendered over every persisted record

**Command:** `uv run python data/logs/2026-08-17-783-reader-render/rerender.py locator`
(the script is in this directory). No model calls, no retrieval, no spend — it
reads `data/papers/*.json` (8) and `data/analyses/*.json` (19), resolves each
ground against `data/vault`, and writes both renderings to `rendered/`.

## Counts

| | |
|---|---|
| records re-rendered | 27 (8 papers, 19 analyses) |
| chunk grounds | 1,301 |
| grounds that resolved a citation | 1,301 (100%) |
| chunk ids in the reader render | 3 |
| `usage_ratio` in the reader render | 0 |
| `[pc-NNN]` markers left in the prose | 0 |
| raw `chunk:` pointers in the reader render | 0 |
| chunk ids in the audit render | 1,317 (unchanged) |
| words | audit 60,908 → reader 49,670 |

## The three chunk ids that remain

All three are in one analysis record, `47f316f6fb04bba7`, and none of them is
rendered by this code. They are inside the counter-position **stance text the
model wrote**:

> …insisting that 'Civil wars do not necessarily or automatically break states;
> they can make them too'
> (malesevic-2026-4faeb528594d_10_forging-statehood-through-inter-and-intra-state-wars_001).

The model cited a chunk id in its own prose. Rewriting model output is not this
issue's job and a render that rewrote prose would stop being a render, so this
is reported rather than smoothed: 3 occurrences, 1 of 27 records, 0 in the 8
paper records.

## Two things the real corpus caught that the issue did not predict

**`chapter` is a heading, not a number.** #786 asked for `Vignal (2021), ch. 30`.
The store's `note_locator` returns `chapter='ANATOMY OF A CONFLICT FROM
REVOLUTION TO WAR'` — the `30` in the chunk id is a section index, not the
book's chapter number. So `ch. <chapter>` would have rendered
`ch. ANATOMY OF A CONFLICT FROM REVOLUTION TO WAR`. The in-text citation is
author and year (`Vignal 2021`); the full form appends whatever locator
resolved, without an invented `ch.` label. No page numbers anywhere, as before.

**Three (c) claims cite nothing, correctly.** `273aea05df54e2df` carries
`pc-029`, `pc-031` and `pc-032` with empty `grounds` — (c) claims run past the
books by definition. Left as raw `[pc-029]` markers they read as broken
references, so a claim with no grounds cites what it is: `(runs past the books)`,
the web client's own legend word for the same kind. A marker whose claim id the
record does not carry at all still renders raw.

## Everything else that ran

- `uv run pytest` (the `src` gate): green.
- `tests/paper`, `tests/analysis`: green.
- `web`: `npm run test` — 39 tests, green.
- `tests/service` needs Postgres and did not run on this box; CI is the gate for
  the export route.
