# #677 slice C — the four reuse counters on merge and gather, validated on the real corpus

2026-08-05. Branch `677c-reuse-counters` (PR #699), run from the worktree
`D:/axial/.claude/worktrees/677c-reuse-counters` against the real 34-book
corpus in `D:/axial/data/`. **Zero model calls, zero writes to `data/names/`.**

## How it was made free and safe

`limit=0`. `to_attempt = pending[:0]` is empty, so the worker pool reaches
nothing, while the counters — computed over the whole of `pending` *before*
`--limit` trims it, which is the decision this slice documented — are still the
real ones. A client that raises on any attribute access is the belt to that
brace. Every write path (alias map, index, manifest, failures, vault,
disagreements copy) was redirected into the worktree scratchpad.

Commands:

```
uv run python scratchpad/validate_677c.py               # console.log
uv run python scratchpad/validate_677c_discriminate.py  # discriminate.log
```

## Pass 1 — the counters compute and the invariants hold

| arm | units_total | units_reused | units_asked | touching_new |
|---|---|---|---|---|
| merge, prior manifest has all 34 books | 13,900 | 13,900 | 0 | 0 |
| merge, prior manifest rewound to 31 | 13,900 | 13,900 | 0 | 0 |
| gather, ledger covers all 34 books | 1,840 | 1,840 | 0 | 0 |
| gather, 683 new-book records removed | 1,840 | 1,157 | 683 | 683 |

`units_asked + units_reused == units_total` in every arm. The corpus is fully
decided, so **rows 1–3 are #677's own "run the pass twice with no corpus change
and get `units_asked: 0`" acceptance bar, met on the real corpus.**

**Neither pass discriminated in this run, and saying so is the point.** Merge
came back 13,900 of 13,900 decided, so `units_asked` was 0 and `touching_new`
had nothing to be a subset of — rewinding the manifest alone cannot make a
batch pending. Gather's 683 was 100% of asked *by construction*: the arm
removed exactly the records touching a new book, so of course every pending
page touched one. A counter that merely re-counted pending work under a second
name would have passed all four rows.

## Pass 2 — the mixed arm, which is the one that proves it

Each ledger loses **both** the units touching one of the three books #623 added
**and** 200 that touch only the 31 already read. A discriminating counter
reports `touching_new` strictly less than `asked`.

| pass | dropped touching new | dropped old-only | units_asked | touching_new | touches only old |
|---|---|---|---|---|---|
| merge | 4,317 | 200 | 2,673 | **2,601** | **72** |
| gather | 683 | 200 | 727 | **683** | **44** |

Both separate. **Gather's precision is exact**: 683 removed, 683 reported, not
one page miscounted. Merge's 2,601/72 split is consistent with its own drop
counts once the two mismatches below are accounted for.

## Two things this surfaced that are worth keeping

**A dropped ledger record does not become a pending unit one-for-one.** Merge
dropped 4,517 decisions and got 2,673 pending batches; gather dropped 883
records and got 727 pending names, of which only 44 came from the 200 old-only
drops. Both are expected — a decision log accumulates records across runs, and
only the ones whose batch or name is still in today's scope can go pending —
but it means **a re-ask count can never be read off a decision-log diff**. Take
it off the counters, which is what they are for.

**Merge's decision log holds 33,337 records for 13,900 current batches**, 2.4x.
Of those records, 4,317 (12.9%) involve a surface form touching one of the
three books added in #623. Not a defect; recorded because the ratio is the kind
of thing that gets misread as re-ask waste later.

## Caveat on the merge arm

`merge_manifest.json` predates the `source_ids` field, so pass 1 had to seed
the "all 34" prior set from the run's own coverage before it could rewind it.
The first real merge run after this merges will write the field itself, and
from then on the comparison is against a genuinely prior run. **The next book
added is the first honest end-to-end measurement of merge's `touching_new`**;
everything here is the mechanism validated by construction.

## Result

Counters correct, invariants hold, both fields discriminate on the real corpus,
nothing spent. CI green on all four jobs.
